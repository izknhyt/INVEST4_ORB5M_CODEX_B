from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, TYPE_CHECKING

from router.router_v0 import pass_gates
from core.sizing import compute_qty_from_ctx

if TYPE_CHECKING:
    from core.runner import BacktestRunner
    from core.runner_features import FeatureBundle


@dataclass
class GateCheckOutcome:
    passed: bool
    reason: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EntryEvaluation:
    outcome: GateCheckOutcome
    context: Optional[Dict[str, Any]] = None
    pending_side: Optional[str] = None


@dataclass
class EVEvaluation:
    outcome: GateCheckOutcome
    manager: Optional[Any] = None
    ev_lcb: Optional[float] = None
    threshold_lcb: Optional[float] = None
    bypass: bool = False
    context: Optional[Dict[str, Any]] = None


@dataclass
class SizingEvaluation:
    outcome: GateCheckOutcome


@dataclass
class TradeContextSnapshot:
    session: Optional[str] = None
    rv_band: Optional[str] = None
    spread_band: Optional[str] = None
    or_atr_ratio: Optional[float] = None
    min_or_atr_ratio: Optional[float] = None
    ev_lcb: Optional[float] = None
    threshold_lcb: Optional[float] = None
    ev_pass: Optional[bool] = None
    expected_slip_pip: Optional[float] = None
    cost_base: Optional[float] = None
    pip_value: Optional[float] = None
    zscore: Optional[float] = None

    def as_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {}
        if self.session is not None:
            data["session"] = self.session
        if self.rv_band is not None:
            data["rv_band"] = self.rv_band
        if self.spread_band is not None:
            data["spread_band"] = self.spread_band
        if self.or_atr_ratio is not None:
            data["or_atr_ratio"] = self.or_atr_ratio
        if self.min_or_atr_ratio is not None:
            data["min_or_atr_ratio"] = self.min_or_atr_ratio
        if self.ev_lcb is not None:
            data["ev_lcb"] = self.ev_lcb
        if self.threshold_lcb is not None:
            data["threshold_lcb"] = self.threshold_lcb
        if self.ev_pass is not None:
            data["ev_pass"] = self.ev_pass
        if self.expected_slip_pip is not None:
            data["expected_slip_pip"] = self.expected_slip_pip
        if self.cost_base is not None:
            data["cost_base"] = self.cost_base
        if self.pip_value is not None:
            data["pip_value"] = self.pip_value
        if self.zscore is not None:
            data["zscore"] = self.zscore
        return data


def build_trade_context_snapshot(
    *,
    ctx_dbg: Mapping[str, Any],
    features_ctx: Mapping[str, Any],
    bar_input: Mapping[str, Any],
) -> TradeContextSnapshot:
    base_cost = features_ctx.get("base_cost_pips", features_ctx.get("cost_pips", 0.0))
    pip_value = features_ctx.get("pip_value")
    if pip_value is None:
        pip_value = ctx_dbg.get("pip_value")
    snapshot = TradeContextSnapshot(
        session=ctx_dbg.get("session", features_ctx.get("session")),
        rv_band=ctx_dbg.get("rv_band", features_ctx.get("rv_band")),
        spread_band=ctx_dbg.get("spread_band", features_ctx.get("spread_band")),
        or_atr_ratio=ctx_dbg.get("or_atr_ratio", features_ctx.get("or_atr_ratio")),
        min_or_atr_ratio=ctx_dbg.get("min_or_atr_ratio", features_ctx.get("min_or_atr_ratio")),
        ev_lcb=ctx_dbg.get("ev_lcb"),
        threshold_lcb=ctx_dbg.get("threshold_lcb"),
        ev_pass=ctx_dbg.get("ev_pass"),
        expected_slip_pip=features_ctx.get("expected_slip_pip", 0.0),
        cost_base=base_cost,
        pip_value=pip_value,
    )
    if "zscore" in bar_input:
        try:
            snapshot.zscore = float(bar_input["zscore"])
        except (TypeError, ValueError):
            snapshot.zscore = bar_input["zscore"]
    return snapshot


class EntryGate:
    def __init__(self, runner: "BacktestRunner") -> None:
        self._runner = runner

    def evaluate(self, *, pending: Any, features: "FeatureBundle") -> EntryEvaluation:
        ctx_dbg = dict(features.ctx)
        pending_side, _, _ = self._runner._extract_pending_fields(pending)
        gate_allowed, gate_reason = self._runner._call_strategy_gate(
            ctx_dbg,
            pending,
            ts=self._runner._last_timestamp,
            side=pending_side,
        )
        if not gate_allowed:
            self._runner.debug_counts["gate_block"] += 1
            self._runner._increment_daily("gate_block")
            metadata: Dict[str, Any] = {}
            if isinstance(gate_reason, Mapping):
                metadata = {
                    "reason_stage": gate_reason.get("stage"),
                    "or_atr_ratio": gate_reason.get("or_atr_ratio"),
                    "min_or_atr_ratio": gate_reason.get("min_or_atr_ratio"),
                    "rv_band": gate_reason.get("rv_band"),
                }
            self._runner._append_debug_record(
                "strategy_gate",
                ts=self._runner._last_timestamp,
                side=pending_side,
                reason_stage=metadata.get("reason_stage"),
                or_atr_ratio=metadata.get("or_atr_ratio"),
                min_or_atr_ratio=metadata.get("min_or_atr_ratio"),
                rv_band=metadata.get("rv_band"),
                allow_low_rv=ctx_dbg.get("allow_low_rv"),
            )
            return EntryEvaluation(
                outcome=GateCheckOutcome(
                    passed=False,
                    reason="strategy_gate",
                    metadata=metadata,
                ),
                context=None,
                pending_side=pending_side,
            )
        if not pass_gates(ctx_dbg):
            self._runner.debug_counts["gate_block"] += 1
            self._runner._increment_daily("gate_block")
            metadata = {
                "rv_band": ctx_dbg.get("rv_band"),
                "spread_band": ctx_dbg.get("spread_band"),
                "or_atr_ratio": ctx_dbg.get("or_atr_ratio"),
            }
            self._runner._append_debug_record(
                "gate_block",
                ts=self._runner._last_timestamp,
                side=pending_side,
                rv_band=metadata["rv_band"],
                spread_band=metadata["spread_band"],
                or_atr_ratio=metadata["or_atr_ratio"],
                reason="router_gate",
            )
            return EntryEvaluation(
                outcome=GateCheckOutcome(
                    passed=False,
                    reason="router_gate",
                    metadata=metadata,
                ),
                context=None,
                pending_side=pending_side,
            )
        self._runner._increment_daily("gate_pass")
        return EntryEvaluation(
            outcome=GateCheckOutcome(passed=True),
            context=ctx_dbg,
            pending_side=pending_side,
        )


class EVGate:
    def __init__(self, runner: "BacktestRunner") -> None:
        self._runner = runner

    def evaluate(
        self,
        *,
        ctx_dbg: Dict[str, Any],
        pending: Any,
        calibrating: bool,
        timestamp: Optional[str],
    ) -> EVEvaluation:
        pending_side, tp_pips, sl_pips = self._runner._extract_pending_fields(pending)
        ev_key = ctx_dbg.get(
            "ev_key",
            (
                ctx_dbg.get("session"),
                ctx_dbg.get("spread_band"),
                ctx_dbg.get("rv_band"),
            ),
        )
        ev_mgr = self._runner._get_ev_manager(ev_key)
        ev_mode_value = str(ctx_dbg.get("ev_mode", "")).lower()
        if ev_mode_value == "off":
            threshold_lcb = float("-inf")
        else:
            threshold_lcb = self._runner._call_ev_threshold(
                ctx_dbg,
                pending,
                self._runner.rcfg.threshold_lcb_pip,
                ts=timestamp,
                side=pending_side,
            )
        ctx_dbg["threshold_lcb_pip"] = threshold_lcb
        ev_lcb = (
            ev_mgr.ev_lcb_oco(
                float(tp_pips),
                float(sl_pips),
                ctx_dbg["cost_pips"],
            )
            if (tp_pips is not None and sl_pips is not None and not calibrating)
            else 1e9
        )
        ev_bypass = False
        if not calibrating and ev_lcb < threshold_lcb:
            if self._runner._warmup_left > 0:
                ev_bypass = True
                warmup_remaining = int(self._runner._warmup_left)
                self._runner.debug_counts["ev_bypass"] += 1
                self._runner._append_debug_record(
                    "ev_bypass",
                    ts=timestamp,
                    side=pending_side,
                    ev_lcb=ev_lcb,
                    threshold_lcb=threshold_lcb,
                    warmup_left=warmup_remaining,
                    warmup_total=int(self._runner.rcfg.warmup_trades),
                    cost_pips=ctx_dbg.get("cost_pips"),
                    tp_pips=tp_pips,
                    sl_pips=sl_pips,
                )
            else:
                self._runner.debug_counts["ev_reject"] += 1
                self._runner._increment_daily("ev_reject")
                self._runner._append_debug_record(
                    "ev_reject",
                    ts=timestamp,
                    side=pending_side,
                    ev_lcb=ev_lcb,
                    threshold_lcb=threshold_lcb,
                    cost_pips=ctx_dbg.get("cost_pips"),
                    tp_pips=tp_pips,
                    sl_pips=sl_pips,
                )
                return EVEvaluation(
                    outcome=GateCheckOutcome(
                        passed=False,
                        reason="ev_reject",
                        metadata={
                            "ev_lcb": ev_lcb,
                            "threshold_lcb": threshold_lcb,
                        },
                    ),
                    manager=ev_mgr,
                    ev_lcb=ev_lcb,
                    threshold_lcb=threshold_lcb,
                    bypass=False,
                    context=ctx_dbg,
                )
        else:
            self._runner._increment_daily("ev_pass")
        ctx_dbg["ev_lcb"] = ev_lcb
        ctx_dbg["threshold_lcb"] = threshold_lcb
        ctx_dbg["ev_pass"] = not ev_bypass
        return EVEvaluation(
            outcome=GateCheckOutcome(passed=True),
            manager=ev_mgr,
            ev_lcb=ev_lcb,
            threshold_lcb=threshold_lcb,
            bypass=ev_bypass,
            context=ctx_dbg,
        )


class SizingGate:
    def __init__(self, runner: "BacktestRunner") -> None:
        self._runner = runner

    def evaluate(
        self,
        *,
        ctx_dbg: Mapping[str, Any],
        pending: Any,
        ev_result: EVEvaluation,
        calibrating: bool,
        timestamp: Optional[str],
    ) -> SizingEvaluation:
        pending_side, tp_pips, sl_pips = self._runner._extract_pending_fields(pending)
        slip_cap = ctx_dbg.get("slip_cap_pip", self._runner.rcfg.slip_cap_pip)
        expected_slip = ctx_dbg.get("expected_slip_pip", 0.0)
        if expected_slip > slip_cap:
            self._runner.debug_counts["gate_block"] += 1
            self._runner._increment_daily("gate_block")
            metadata = {
                "expected_slip_pip": expected_slip,
                "slip_cap_pip": slip_cap,
            }
            self._runner._append_debug_record(
                "slip_cap",
                ts=timestamp,
                side=pending_side,
                expected_slip_pip=expected_slip,
                slip_cap_pip=slip_cap,
            )
            return SizingEvaluation(
                outcome=GateCheckOutcome(
                    passed=False,
                    reason="slip_cap",
                    metadata=metadata,
                )
            )
        if (
            not ev_result.bypass
            and not calibrating
            and tp_pips is not None
            and sl_pips is not None
        ):
            ctx_for_sizing: Dict[str, Any] = dict(ctx_dbg)
            ctx_for_sizing.setdefault("equity", self._runner._equity_live)
            manager = ev_result.manager
            if manager is None:
                raise ValueError("EV manager is required when sizing evaluation runs")
            qty_dbg = compute_qty_from_ctx(
                ctx_for_sizing,
                float(sl_pips),
                mode="production",
                tp_pips=float(tp_pips),
                p_lcb=manager.p_lcb(),
            )
            if qty_dbg <= 0:
                self._runner.debug_counts["zero_qty"] += 1
                return SizingEvaluation(
                    outcome=GateCheckOutcome(
                        passed=False,
                        reason="zero_qty",
                        metadata={"qty": qty_dbg},
                    )
                )
        return SizingEvaluation(outcome=GateCheckOutcome(passed=True))
