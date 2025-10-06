from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Optional, TYPE_CHECKING, Union

from core.fill_engine import OrderSpec
from core.pips import price_to_pips
from core.runner_entry import EntryContext, EVContext, SizingContext, TradeContextSnapshot
from core.runner_state import (
    ActivePositionState,
    CalibrationPositionState,
    PositionState,
    snapshot_to_dict,
)

if TYPE_CHECKING:
    from core.runner import BacktestRunner


@dataclass
class ExitDecision:
    exited: bool
    exit_px: Optional[float]
    exit_reason: Optional[str]
    updated_pos: Optional[PositionState]


class RunnerExecutionManager:
    """Trade lifecycle orchestration for ``BacktestRunner``."""

    def __init__(self, runner: "BacktestRunner") -> None:
        self._runner = runner

    # ----- Position management ----------------------------------------------------
    def compute_exit_decision(
        self,
        *,
        pos: PositionState,
        bar: Mapping[str, Any],
        mode: str,
        pip_size_value: float,
        new_session: bool,
    ) -> ExitDecision:
        state = pos.apply_trailing_stop(
            high=bar["h"],
            low=bar["l"],
            pip_size=pip_size_value,
        )
        side = state.side
        entry_px = state.entry_px
        tp_px = state.tp_px
        sl_px = state.sl_px
        direction = 1.0 if side == "BUY" else -1.0

        exit_px: Optional[float] = None
        exit_reason: Optional[str] = None
        sl_hit = bar["l"] <= sl_px if side == "BUY" else bar["h"] >= sl_px
        tp_hit = bar["h"] >= tp_px if side == "BUY" else bar["l"] <= tp_px

        if sl_hit and tp_hit:
            if mode == "conservative":
                exit_px, exit_reason = sl_px, "sl"
            else:
                rng = max(bar["h"] - bar["l"], pip_size_value)
                drift = direction * (bar["c"] - bar["o"]) / rng if rng > 0 else 0.0
                d_tp = max(((tp_px - entry_px) * direction) / pip_size_value, 1e-9)
                d_sl = max(((entry_px - sl_px) * direction) / pip_size_value, 1e-9)
                base = d_sl / (d_tp + d_sl)
                p_tp = min(
                    0.999,
                    max(0.001, 0.65 * base + 0.35 * 0.5 * (1.0 + math.tanh(2.5 * drift))),
                )
                exit_px = p_tp * tp_px + (1 - p_tp) * sl_px
                exit_reason = "tp" if p_tp >= 0.5 else "sl"
            exited = True
        elif sl_hit:
            exit_px, exit_reason, exited = sl_px, "sl", True
        elif tp_hit:
            exit_px, exit_reason, exited = tp_px, "tp", True
        else:
            exited = False

        if not exited:
            updated_state = state.increment_hold()
            hold = updated_state.hold
            max_hold = getattr(self._runner.rcfg, "max_hold_bars", 96)
            if new_session or hold >= max_hold:
                exit_px = bar["o"]
                exit_reason = "session_end" if new_session else "timeout"
                exited = True

        if exited:
            return ExitDecision(True, exit_px, exit_reason, None)
        return ExitDecision(False, None, None, updated_state)

    def handle_active_position(
        self,
        *,
        bar: Dict[str, Any],
        ctx: Mapping[str, Any],
        mode: str,
        pip_size_value: float,
        new_session: bool,
    ) -> bool:
        runner = self._runner
        if getattr(runner, "pos", None) is None:
            return False

        current_pos: ActivePositionState = runner.pos
        decision = self.compute_exit_decision(
            pos=current_pos,
            bar=bar,
            mode=mode,
            pip_size_value=pip_size_value,
            new_session=new_session,
        )
        runner.pos = decision.updated_pos

        if decision.exited and decision.exit_px is not None:
            qty_sample = current_pos.qty if current_pos.qty else 1.0
            slip_actual = current_pos.entry_slip_pip
            self.finalize_trade(
                exit_ts=bar.get("timestamp"),
                entry_ts=current_pos.entry_ts,
                side=current_pos.side,
                entry_px=current_pos.entry_px,
                exit_px=decision.exit_px,
                exit_reason=decision.exit_reason,
                ctx_snapshot=current_pos.ctx_snapshot_dict(),
                ctx=ctx,
                qty_sample=qty_sample,
                slip_actual=slip_actual,
                ev_key=current_pos.ev_key,
                tp_pips=current_pos.tp_pips or 0.0,
                sl_pips=current_pos.sl_pips or 0.0,
                debug_stage="trade_exit",
            )

        return True

    def resolve_calibration_positions(
        self,
        *,
        bar: Dict[str, Any],
        ctx: Mapping[str, Any],
        new_session: bool,
        calibrating: bool,
        mode: str,
        pip_size_value: float,
    ) -> None:
        runner = self._runner
        if not runner.calib_positions:
            return
        still: list[CalibrationPositionState] = []
        for pos_state in runner.calib_positions:
            decision = self.compute_exit_decision(
                pos=pos_state,
                bar=bar,
                mode=mode,
                pip_size_value=pip_size_value,
                new_session=new_session,
            )
            ev_key = pos_state.ev_key or ctx.get("ev_key") or (
                ctx.get("session"),
                ctx.get("spread_band"),
                ctx.get("rv_band"),
            )
            if decision.exited:
                hit = decision.exit_reason == "tp"
                runner._get_ev_manager(ev_key).update(bool(hit))
                continue
            updated_state = decision.updated_pos or pos_state
            if not isinstance(updated_state, CalibrationPositionState):
                updated_state = CalibrationPositionState.from_dict(updated_state.as_dict())
            still.append(updated_state)
        runner.calib_positions = still

    # ----- Fill processing --------------------------------------------------------
    def maybe_enter_trade(
        self,
        *,
        bar: Dict[str, Any],
        features: Any,
        mode: str,
        pip_size_value: float,
        calibrating: bool,
    ) -> None:
        runner = self._runner
        runner.stg.on_bar(features.bar_input)
        pending = getattr(runner.stg, "_pending_signal", None)
        if pending is None:
            runner.debug_counts["no_breakout"] += 1
            runner._append_debug_record("no_breakout", ts=runner._last_timestamp)
            return
        runner._increment_daily("breakouts")
        entry_result = runner._evaluate_entry_conditions(
            pending=pending,
            features=features,
        )
        if not entry_result.outcome.passed or entry_result.context is None:
            return
        entry_ctx = entry_result.context
        features.ctx.update(entry_ctx.to_mapping())
        ev_result = runner._evaluate_ev_threshold(
            ctx=entry_ctx,
            pending=pending,
            calibrating=calibrating,
            timestamp=runner._last_timestamp,
        )
        if not ev_result.outcome.passed:
            return
        ev_ctx = ev_result.context or EVContext.from_entry(entry_ctx)
        features.ctx.update(ev_ctx.to_mapping())
        sizing_result = runner._check_slip_and_sizing(
            ctx=ev_ctx,
            pending=pending,
            ev_result=ev_result,
            calibrating=calibrating,
            timestamp=runner._last_timestamp,
        )
        if not sizing_result.outcome.passed:
            return
        sizing_ctx = sizing_result.context or SizingContext.from_ev(ev_ctx)
        features.ctx.update(sizing_ctx.to_mapping())
        intents = list(runner.stg.signals())
        if not intents:
            runner.debug_counts["gate_block"] += 1
            return
        intent = intents[0]
        spec = OrderSpec(
            side=intent.side,
            entry=intent.price,
            tp_pips=intent.oco["tp_pips"],
            sl_pips=intent.oco["sl_pips"],
            trail_pips=intent.oco.get("trail_pips", 0.0),
            slip_cap_pip=features.ctx["slip_cap_pip"],
        )
        fill_engine = runner.fill_engine_c if mode == "conservative" else runner.fill_engine_b
        result = fill_engine.simulate(
            {
                "o": bar["o"],
                "h": bar["h"],
                "l": bar["l"],
                "c": bar["c"],
                "pip": pip_size_value,
                "spread": bar["spread"],
            },
            spec,
        )
        if not result.get("fill"):
            return
        trade_ctx_snapshot = runner._compose_trade_context_snapshot(
            ctx=sizing_ctx,
            features=features,
        )
        state = self.process_fill_result(
            intent=intent,
            spec=spec,
            result=result,
            bar=bar,
            ctx=features.ctx,
            ctx_dbg=sizing_ctx,
            trade_ctx_snapshot=trade_ctx_snapshot,
            calibrating=calibrating,
            pip_size_value=pip_size_value,
        )
        if not calibrating and runner._warmup_left > 0:
            runner._warmup_left -= 1

    def process_fill_result(
        self,
        *,
        intent: Any,
        spec: OrderSpec,
        result: Mapping[str, Any],
        bar: Mapping[str, Any],
        ctx: Mapping[str, Any],
        ctx_dbg: Union[EntryContext, EVContext, SizingContext],
        trade_ctx_snapshot: TradeContextSnapshot,
        calibrating: bool,
        pip_size_value: float,
    ) -> Optional[PositionState]:
        runner = self._runner
        if "exit_px" in result:
            entry_px = result["entry_px"]
            exit_px = result["exit_px"]
            exit_reason = result.get("exit_reason")
            if calibrating:
                hit = exit_reason == "tp"
                ev_key = ctx.get("ev_key") or (
                    ctx.get("session"),
                    ctx.get("spread_band"),
                    ctx.get("rv_band"),
                )
                runner._get_ev_manager(ev_key).update(bool(hit))
                return None
            qty_sample, slip_actual = runner._update_slip_learning(
                order=intent,
                actual_price=entry_px,
                intended_price=intent.price,
                ctx=ctx,
            )
            self.finalize_trade(
                exit_ts=bar.get("timestamp"),
                entry_ts=bar.get("timestamp"),
                side=intent.side,
                entry_px=entry_px,
                exit_px=exit_px,
                exit_reason=exit_reason,
                ctx_snapshot=trade_ctx_snapshot,
                ctx=ctx,
                qty_sample=qty_sample,
                slip_actual=slip_actual,
                ev_key=ctx.get("ev_key"),
                tp_pips=spec.tp_pips,
                sl_pips=spec.sl_pips,
                debug_stage="trade",
                debug_extra={
                    "tp_pips": spec.tp_pips,
                    "sl_pips": spec.sl_pips,
                },
            )
            return None
        entry_px_result = result.get("entry_px")
        entry_px = entry_px_result if entry_px_result is not None else intent.price
        if entry_px is None:
            raise ValueError("Filled entry price is required to initialise position state")
        direction = 1.0 if intent.side == "BUY" else -1.0
        tp_px = entry_px + direction * spec.tp_pips * pip_size_value
        sl_px0 = entry_px - direction * spec.sl_pips * pip_size_value
        if calibrating:
            state = CalibrationPositionState(
                side=intent.side,
                entry_px=entry_px,
                tp_px=tp_px,
                sl_px=sl_px0,
                trail_pips=spec.trail_pips,
                tp_pips=spec.tp_pips,
                sl_pips=spec.sl_pips,
                hh=bar["h"],
                ll=bar["l"],
                ev_key=ctx.get("ev_key"),
                ctx_snapshot=trade_ctx_snapshot,
            )
            runner.calib_positions.append(state)
            return state
        _, entry_slip_pip = runner._update_slip_learning(
            order=intent,
            actual_price=entry_px,
            intended_price=intent.price,
            ctx=ctx,
        )
        state = ActivePositionState(
            side=intent.side,
            entry_px=entry_px,
            tp_px=tp_px,
            sl_px=sl_px0,
            tp_pips=spec.tp_pips,
            sl_pips=spec.sl_pips,
            trail_pips=spec.trail_pips,
            hh=bar["h"],
            ll=bar["l"],
            ev_key=ctx.get("ev_key"),
            qty=getattr(intent, "qty", 1.0) or 1.0,
            expected_slip_pip=ctx.get("expected_slip_pip", 0.0),
            entry_slip_pip=entry_slip_pip,
            entry_ts=bar.get("timestamp"),
            ctx_snapshot=trade_ctx_snapshot,
        )
        runner.pos = state
        return state

    # ----- Trade finalisation -----------------------------------------------------
    def log_trade_record(
        self,
        *,
        exit_ts: Any,
        entry_ts: Any,
        side: str,
        tp_pips: float,
        sl_pips: float,
        cost_pips: float,
        slip_est: float,
        slip_real: float,
        exit_reason: Optional[str],
        pnl_pips: float,
        pnl_value: float,
        qty: float,
        ctx_snapshot: Union[Mapping[str, Any], TradeContextSnapshot, None] = None,
    ) -> None:
        runner = self._runner
        ctx_snapshot_map = snapshot_to_dict(ctx_snapshot)
        record = {
            "ts": exit_ts,
            "entry_ts": entry_ts,
            "stage": "trade",
            "side": side,
            "tp_pips": tp_pips,
            "sl_pips": sl_pips,
            "cost_pips": cost_pips,
            "slip_est": slip_est,
            "slip_real": slip_real,
            "exit": exit_reason,
            "pnl_pips": pnl_pips,
            "pnl_value": pnl_value,
            "qty": qty,
        }
        for key in (
            "session",
            "rv_band",
            "spread_band",
            "or_atr_ratio",
            "min_or_atr_ratio",
            "ev_lcb",
            "threshold_lcb",
            "ev_pass",
            "expected_slip_pip",
            "zscore",
        ):
            value = ctx_snapshot_map.get(key)
            if value is not None:
                record[key] = value
        if ctx_snapshot_map.get("cost_base") is not None:
            record["cost_base"] = ctx_snapshot_map["cost_base"]
        runner.records.append(record)

    def finalize_trade(
        self,
        *,
        exit_ts: Any,
        entry_ts: Any,
        side: str,
        entry_px: float,
        exit_px: float,
        exit_reason: Optional[str],
        ctx_snapshot: Union[Mapping[str, Any], TradeContextSnapshot],
        ctx: Mapping[str, Any],
        qty_sample: float,
        slip_actual: float,
        ev_key: Optional[Iterable[Any]],
        tp_pips: float,
        sl_pips: float,
        debug_stage: str,
        debug_extra: Optional[Mapping[str, Any]] = None,
    ) -> None:
        runner = self._runner
        ctx_snapshot_map = snapshot_to_dict(ctx_snapshot)
        base_cost = ctx_snapshot_map.get(
            "cost_base", ctx.get("base_cost_pips", ctx.get("cost_pips", 0.0))
        )
        est_slip_used = 0.0
        if getattr(runner.rcfg, "include_expected_slip", False):
            band = ctx_snapshot_map.get(
                "spread_band", ctx.get("spread_band", "normal")
            )
            coeff = float(
                runner.slip_a.get(
                    band, runner.rcfg.slip_curve.get(band, {}).get("a", 0.0)
                )
            )
            intercept = float(runner.rcfg.slip_curve.get(band, {}).get("b", 0.0))
            est_slip_used = max(0.0, coeff * qty_sample + intercept)
        cost = base_cost + est_slip_used
        signed = 1 if side == "BUY" else -1
        pnl_px = (exit_px - entry_px) * signed
        pnl_pips_unit = price_to_pips(pnl_px, runner.symbol) - cost
        try:
            qty_effective = float(qty_sample)
        except (TypeError, ValueError):
            qty_effective = 0.0
        pnl_pips = pnl_pips_unit * qty_effective
        hit = exit_reason == "tp"
        pip_value_ctx = ctx_snapshot_map.get("pip_value")
        if pip_value_ctx is None:
            pip_value_ctx = ctx.get("pip_value", 10.0)
        try:
            pip_value_float = float(pip_value_ctx)
        except (TypeError, ValueError):
            pip_value_float = 0.0
        pnl_value = pnl_pips_unit * pip_value_float * qty_effective
        runner._equity_live += pnl_value
        self.record_trade_metrics(
            pnl_pips,
            hit,
            timestamp=exit_ts,
            pnl_value=pnl_value,
        )
        runner._increment_daily("fills")
        if hit:
            runner._increment_daily("wins")
        runner._increment_daily("pnl_pips", pnl_pips)
        runner._increment_daily("pnl_value", pnl_value)
        runner._increment_daily("slip_est", est_slip_used)
        runner._increment_daily("slip_real", slip_actual)
        session = ctx.get("session", "TOK")
        spread_band = ctx.get("spread_band", "normal")
        rv_band = ctx.get("rv_band")
        resolved_key = ev_key or ctx.get("ev_key") or (session, spread_band, rv_band)
        if resolved_key:
            runner._get_ev_manager(tuple(resolved_key)).update(hit)
        self.log_trade_record(
            exit_ts=exit_ts,
            entry_ts=entry_ts,
            side=side,
            tp_pips=tp_pips,
            sl_pips=sl_pips,
            cost_pips=cost,
            slip_est=est_slip_used,
            slip_real=slip_actual,
            exit_reason=exit_reason,
            pnl_pips=pnl_pips,
            pnl_value=pnl_value,
            qty=qty_effective,
            ctx_snapshot=ctx_snapshot,
        )
        debug_fields = {
            "ts": runner._last_timestamp,
            "side": side,
            "cost_pips": cost,
            "slip_est": est_slip_used,
            "slip_real": slip_actual,
            "exit": exit_reason,
            "pnl_pips": pnl_pips,
            "pnl_value": pnl_value,
        }
        if debug_extra:
            debug_fields.update(debug_extra)
        runner._append_debug_record(debug_stage, **debug_fields)
        runner.ev_var.update(pnl_pips)

    def record_trade_metrics(
        self,
        pnl_pips: float,
        hit: bool,
        *,
        timestamp: Any,
        pnl_value: Optional[float] = None,
    ) -> None:
        runner = self._runner
        runner.metrics.record_trade(
            pnl_pips,
            hit,
            timestamp=timestamp,
            pnl_value=pnl_value,
        )

