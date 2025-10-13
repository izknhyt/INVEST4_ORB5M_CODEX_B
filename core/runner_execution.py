from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Optional, TYPE_CHECKING, Union, cast

from core.fill_engine import BridgeFill, OrderSpec, resolve_same_bar_collision
from core.pips import price_to_pips
from core.runner_entry import EntryContext, EVContext, SizingContext, TradeContextSnapshot
from core.runner_state import (
    ActivePositionState,
    CalibrationPositionState,
    PositionState,
    normalize_ev_key,
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
    p_tp: Optional[float] = None


class RunnerExecutionManager:
    """Trade lifecycle orchestration for ``BacktestRunner``."""

    def __init__(self, runner: "BacktestRunner") -> None:
        self._runner = runner
        self._PNL_EPSILON = 1e-9

    @staticmethod
    def _default_ev_key(ctx: Mapping[str, Any]) -> tuple[str, str, Optional[Any]]:
        session_raw = ctx.get("session")
        if isinstance(session_raw, str) and session_raw:
            session = session_raw
        elif session_raw is not None:
            session = str(session_raw)
        else:
            session = "TOK"
        spread_raw = ctx.get("spread_band")
        if isinstance(spread_raw, str) and spread_raw:
            spread = spread_raw
        elif spread_raw is not None:
            spread = str(spread_raw)
        else:
            spread = "normal"
        rv_raw = ctx.get("rv_band")
        if rv_raw is None or isinstance(rv_raw, str):
            rv = rv_raw
        else:
            rv = str(rv_raw)
        return (session, spread, rv)

    @staticmethod
    def _coerce_probability(value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            prob = float(value)
        except (TypeError, ValueError):
            return None
        if math.isnan(prob):
            return None
        if prob < 0.0:
            return 0.0
        if prob > 1.0:
            return 1.0
        return prob

    def _is_win_after_cost(self, exit_reason: Optional[str], pnl_pips: float) -> bool:
        if exit_reason == "tp":
            return True
        if exit_reason == "trail" and pnl_pips > self._PNL_EPSILON:
            return True
        return False

    def _net_pnl_pips(
        self,
        *,
        side: str,
        entry_px: float,
        exit_px: float,
        ctx: Mapping[str, Any],
    ) -> float:
        direction = 1.0 if side == "BUY" else -1.0
        price_move = (exit_px - entry_px) * direction
        pnl_pips = price_to_pips(price_move, self._runner.symbol)
        base_cost = ctx.get("cost_pips", ctx.get("base_cost_pips", 0.0))
        try:
            cost_value = float(base_cost)
        except (TypeError, ValueError):
            cost_value = 0.0
        return pnl_pips - cost_value

    @staticmethod
    def _should_count_ev_pass(ev_result: Any, calibrating: bool) -> bool:
        """Determine whether EV pass metrics should increment."""
        outcome = getattr(ev_result, "outcome", None)
        if outcome is None or not getattr(outcome, "passed", False):
            return False
        if calibrating:
            return True
        bypass = bool(getattr(ev_result, "bypass", False))
        if not bypass:
            return True
        ev_lcb = getattr(ev_result, "ev_lcb", None)
        threshold = getattr(ev_result, "threshold_lcb", None)
        if ev_lcb is None or threshold is None:
            return True
        try:
            return float(ev_lcb) >= float(threshold)
        except (TypeError, ValueError):
            return True

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
        original_sl = pos.sl_px
        stop_reason = "sl"
        if pos.trail_pips > 0.0:
            if side == "BUY" and state.sl_px > original_sl + 1e-9:
                stop_reason = "trail"
            elif side == "SELL" and state.sl_px < original_sl - 1e-9:
                stop_reason = "trail"
        sl_hit = bar["l"] <= sl_px if side == "BUY" else bar["h"] >= sl_px
        tp_hit = bar["h"] >= tp_px if side == "BUY" else bar["l"] <= tp_px

        if sl_hit and tp_hit:
            policy = self._runner.rcfg.resolve_same_bar_policy(mode)
            if mode == "conservative":
                lam = getattr(self._runner.fill_engine_c, "lam", BridgeFill.DEFAULT_LAM)
                drift_scale = getattr(
                    self._runner.fill_engine_c,
                    "drift_scale",
                    BridgeFill.DEFAULT_DRIFT_SCALE,
                )
                include_prob = False
            else:
                lam = BridgeFill._config_value(
                    self._runner.rcfg, "fill_bridge_lambda", BridgeFill.DEFAULT_LAM
                )
                drift_scale = BridgeFill._config_value(
                    self._runner.rcfg,
                    "fill_bridge_drift_scale",
                    BridgeFill.DEFAULT_DRIFT_SCALE,
                )
                include_prob = True

            exit_px, exit_reason, p_tp = resolve_same_bar_collision(
                policy=policy,
                side=side,
                entry_px=entry_px,
                tp_px=tp_px,
                stop_px=sl_px,
                stop_reason=stop_reason,
                bar=bar,
                pip_size=pip_size_value,
                lam=float(lam),
                drift_scale=float(drift_scale),
                include_prob=include_prob,
            )
            exited = True
        elif sl_hit:
            exit_px, exit_reason, exited, p_tp = sl_px, stop_reason, True, None
        elif tp_hit:
            exit_px, exit_reason, exited, p_tp = tp_px, "tp", True, None
        else:
            exited = False
            p_tp = None

        if not exited:
            updated_state = state.increment_hold()
            hold = updated_state.hold
            max_hold = getattr(self._runner.rcfg, "max_hold_bars", 96)
            if new_session or hold >= max_hold:
                exit_px = bar["o"]
                exit_reason = "session_end" if new_session else "timeout"
                exited = True
                p_tp = None

        if exited:
            return ExitDecision(True, exit_px, exit_reason, None, p_tp)
        return ExitDecision(False, None, None, updated_state, None)

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
            debug_extra: Optional[Mapping[str, Any]] = None
            if decision.p_tp is not None:
                debug_extra = {"same_bar_p_tp": decision.p_tp}
            finalize_args = dict(
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
                debug_extra=debug_extra,
            )
            prob = self._coerce_probability(decision.p_tp)
            if prob is not None:
                finalize_args["p_tp"] = prob
            self.finalize_trade(**finalize_args)

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
            default_key = self._default_ev_key(ctx)
            ev_key = normalize_ev_key(pos_state.ev_key)
            if ev_key is None:
                ev_key = normalize_ev_key(ctx.get("ev_key"))
            if ev_key is None:
                ev_key = default_key
            if decision.exited:
                manager = runner._get_ev_manager(ev_key)
                prob = self._coerce_probability(decision.p_tp)
                if prob is not None:
                    manager.update_weighted(prob)
                else:
                    exit_px = decision.exit_px
                    if exit_px is None:
                        manager.update(False)
                    else:
                        pnl_unit = self._net_pnl_pips(
                            side=pos_state.side,
                            entry_px=pos_state.entry_px,
                            exit_px=exit_px,
                            ctx=ctx,
                        )
                        manager.update(
                            self._is_win_after_cost(decision.exit_reason, pnl_unit)
                        )
                continue
            updated_state = cast(
                CalibrationPositionState, decision.updated_pos or pos_state
            )
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
        pending = runner.stg.get_pending_signal()
        if pending is None:
            runner.debug_counts["no_breakout"] += 1
            runner._append_debug_record("no_breakout", ts=runner._last_timestamp)
            return
        entry_result = runner._evaluate_entry_conditions(
            pending=pending,
            features=features,
        )
        if not entry_result.outcome.passed:
            return
        entry_ctx = entry_result.context
        entry_result.apply_to(features.ctx)
        ev_result = runner._evaluate_ev_threshold(
            entry=entry_result,
            pending=pending,
            calibrating=calibrating,
            timestamp=runner._last_timestamp,
        )
        if not ev_result.outcome.passed:
            return
        ev_ctx = ev_result.context
        ev_result.apply_to(features.ctx)
        sizing_result = runner._check_slip_and_sizing(
            ctx=ev_ctx,
            ev_result=ev_result,
            calibrating=calibrating,
            timestamp=runner._last_timestamp,
        )
        if not sizing_result.outcome.passed:
            return
        sizing_ctx = sizing_result.context
        sizing_result.apply_to(features.ctx)
        runner.stg.update_context(features.ctx.to_dict())
        intents = list(runner.stg.signals())
        if not intents:
            runner.debug_counts["gate_block"] += 1
            runner._increment_daily("gate_block")
            return

        fill_engine = (
            runner.fill_engine_c if mode == "conservative" else runner.fill_engine_b
        )
        bar_ctx = {
            "o": bar["o"],
            "h": bar["h"],
            "l": bar["l"],
            "c": bar["c"],
            "pip": pip_size_value,
            "spread": bar["spread"],
        }

        current_ev_result = ev_result
        base_sizing_ctx = sizing_ctx
        gate_pass_count = 0
        ev_pass_count = 0

        for index, intent in enumerate(intents):
            if (
                not calibrating
                and current_ev_result.bypass
                and runner._warmup_left <= 0
            ):
                fresh_ev_result = runner._evaluate_ev_threshold(
                    entry=entry_result,
                    pending=pending,
                    calibrating=calibrating,
                    timestamp=runner._last_timestamp,
                )
                if not fresh_ev_result.outcome.passed:
                    break
                fresh_ev_result.apply_to(features.ctx)
                fresh_sizing_result = runner._check_slip_and_sizing(
                    ctx=fresh_ev_result.context,
                    ev_result=fresh_ev_result,
                    calibrating=calibrating,
                    timestamp=runner._last_timestamp,
                )
                if not fresh_sizing_result.outcome.passed:
                    break
                fresh_sizing_result.apply_to(features.ctx)
                current_ev_result = fresh_ev_result
                base_sizing_ctx = fresh_sizing_result.context

            gate_pass_count += 1
            if self._should_count_ev_pass(current_ev_result, calibrating):
                ev_pass_count += 1

            if index == 0:
                ctx_for_intent = base_sizing_ctx
            else:
                ctx_for_intent = SizingContext(**base_sizing_ctx._constructor_kwargs())

            runner._increment_daily("breakouts")
            spec = OrderSpec(
                side=intent.side,
                entry=intent.price,
                tp_pips=intent.oco["tp_pips"],
                sl_pips=intent.oco["sl_pips"],
                trail_pips=intent.oco.get("trail_pips", 0.0),
                slip_cap_pip=features.ctx["slip_cap_pip"],
            )
            result = fill_engine.simulate(bar_ctx, spec)
            if not result.get("fill"):
                continue
            trade_ctx_snapshot = runner._compose_trade_context_snapshot(
                ctx=ctx_for_intent,
                features=features,
            )
            self.process_fill_result(
                intent=intent,
                spec=spec,
                result=result,
                bar=bar,
                ctx=features.ctx,
                ctx_dbg=ctx_for_intent,
                trade_ctx_snapshot=trade_ctx_snapshot,
                calibrating=calibrating,
                pip_size_value=pip_size_value,
            )
            if not calibrating and runner._warmup_left > 0:
                runner._warmup_left -= 1

        if gate_pass_count:
            runner._increment_daily("gate_pass", gate_pass_count)
            if ev_pass_count:
                runner._increment_daily("ev_pass", ev_pass_count)

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
            prob = self._coerce_probability(result.get("p_tp"))
            if calibrating:
                ev_key = ctx.get("ev_key") or (
                    ctx.get("session"),
                    ctx.get("spread_band"),
                    ctx.get("rv_band"),
                )
                manager = runner._get_ev_manager(ev_key)
                if prob is not None:
                    manager.update_weighted(prob)
                else:
                    pnl_unit = self._net_pnl_pips(
                        side=intent.side,
                        entry_px=entry_px,
                        exit_px=exit_px,
                        ctx=ctx,
                    )
                    manager.update(
                        self._is_win_after_cost(exit_reason, pnl_unit)
                    )
                return None
            qty_sample, slip_actual = runner._update_slip_learning(
                order=intent,
                actual_price=entry_px,
                intended_price=intent.price,
                ctx=ctx,
            )
            finalize_args = dict(
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
            if prob is not None:
                finalize_args["p_tp"] = prob
            self.finalize_trade(**finalize_args)
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
        p_tp: Optional[float] = None,
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
        hit = self._is_win_after_cost(exit_reason, pnl_pips)
        prob = self._coerce_probability(p_tp)
        if prob is not None:
            win_increment = prob
        else:
            win_increment = 1.0 if hit else 0.0
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
            win_increment,
            timestamp=exit_ts,
            pnl_value=pnl_value,
        )
        runner._increment_daily("fills")
        if win_increment:
            runner._increment_daily("wins", win_increment)
        runner._increment_daily("pnl_pips", pnl_pips)
        runner._increment_daily("pnl_value", pnl_value)
        runner._increment_daily("slip_est", est_slip_used)
        runner._increment_daily("slip_real", slip_actual)
        runner._daily_trade_count += 1
        runner._daily_pnl_pips += pnl_pips
        if pnl_pips <= 0:
            runner._loss_streak += 1
            if pnl_pips < 0:
                runner._daily_loss_pips += pnl_pips
        else:
            runner._loss_streak = 0
        default_key = self._default_ev_key(ctx)
        resolved_key = normalize_ev_key(ev_key)
        if resolved_key is None:
            resolved_key = normalize_ev_key(ctx.get("ev_key"))
        if resolved_key is None:
            resolved_key = default_key
        if resolved_key:
            manager = runner._get_ev_manager(resolved_key)
            if prob is not None:
                manager.update_weighted(prob)
            else:
                manager.update(hit)
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
        win_increment: float,
        *,
        timestamp: Any,
        pnl_value: Optional[float] = None,
    ) -> None:
        runner = self._runner
        runner.metrics.record_trade(
            pnl_pips,
            win_increment,
            timestamp=timestamp,
            pnl_value=pnl_value,
        )
