from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Tuple, TYPE_CHECKING, Union

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
class EntryContext:
    session: str
    spread_band: str
    rv_band: str
    slip_cap_pip: float
    threshold_lcb_pip: float
    or_atr_ratio: float
    min_or_atr_ratio: float
    allow_low_rv: bool
    warmup_left: float
    warmup_mult: float
    cooldown_bars: int
    ev_mode: str
    size_floor_mult: float
    base_cost_pips: float
    expected_slip_pip: float
    cost_pips: float
    equity: float
    pip_value: float
    sizing_cfg: Dict[str, Any]
    ev_key: Tuple[str, str, str]
    ev_manager: Any
    ev_profile_stats: Optional[Mapping[str, Any]] = None
    allowed_sessions: Optional[Tuple[str, ...]] = None
    news_freeze: bool = False
    calibrating: bool = False

    def _constructor_kwargs(self) -> Dict[str, Any]:
        data = dict(vars(self))
        sizing_cfg = data.get("sizing_cfg")
        if isinstance(sizing_cfg, dict):
            data["sizing_cfg"] = dict(sizing_cfg)
        return data

    def to_mapping(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "session": self.session,
            "spread_band": self.spread_band,
            "rv_band": self.rv_band,
            "slip_cap_pip": self.slip_cap_pip,
            "threshold_lcb_pip": self.threshold_lcb_pip,
            "or_atr_ratio": self.or_atr_ratio,
            "min_or_atr_ratio": self.min_or_atr_ratio,
            "allow_low_rv": self.allow_low_rv,
            "warmup_left": self.warmup_left,
            "warmup_mult": self.warmup_mult,
            "cooldown_bars": self.cooldown_bars,
            "ev_mode": self.ev_mode,
            "size_floor_mult": self.size_floor_mult,
            "base_cost_pips": self.base_cost_pips,
            "expected_slip_pip": self.expected_slip_pip,
            "cost_pips": self.cost_pips,
            "equity": self.equity,
            "pip_value": self.pip_value,
            "sizing_cfg": dict(self.sizing_cfg),
            "ev_key": self.ev_key,
            "ev_oco": self.ev_manager,
        }
        if self.allowed_sessions is not None:
            data["allowed_sessions"] = list(self.allowed_sessions)
        if self.ev_profile_stats is not None:
            data["ev_profile_stats"] = self.ev_profile_stats
        if self.news_freeze:
            data["news_freeze"] = self.news_freeze
        if self.calibrating:
            data["calibrating"] = self.calibrating
        return data


@dataclass
class EVContext(EntryContext):
    ev_lcb: Optional[float] = None
    threshold_lcb: Optional[float] = None
    ev_pass: Optional[bool] = None
    bypass: bool = False

    @classmethod
    def from_entry(cls, entry: EntryContext) -> "EVContext":
        return cls(**entry._constructor_kwargs())

    def to_mapping(self) -> Dict[str, Any]:  # type: ignore[override]
        data = super().to_mapping()
        if self.ev_lcb is not None:
            data["ev_lcb"] = self.ev_lcb
        if self.threshold_lcb is not None:
            data["threshold_lcb"] = self.threshold_lcb
        if self.ev_pass is not None:
            data["ev_pass"] = self.ev_pass
        data["ev_bypass"] = self.bypass
        return data


@dataclass
class SizingContext(EVContext):
    qty: Optional[float] = None

    @classmethod
    def from_ev(cls, ev_ctx: EVContext) -> "SizingContext":
        return cls(**ev_ctx._constructor_kwargs())

    def to_mapping(self) -> Dict[str, Any]:  # type: ignore[override]
        data = super().to_mapping()
        if self.qty is not None:
            data["qty"] = self.qty
        return data


@dataclass
class EntryEvaluation:
    outcome: GateCheckOutcome
    context: Optional[EntryContext] = None
    pending_side: Optional[str] = None


@dataclass
class EVEvaluation:
    outcome: GateCheckOutcome
    manager: Optional[Any] = None
    ev_lcb: Optional[float] = None
    threshold_lcb: Optional[float] = None
    bypass: bool = False
    context: Optional[EVContext] = None


@dataclass
class SizingEvaluation:
    outcome: GateCheckOutcome
    context: Optional[SizingContext] = None


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


ContextType = Union[EntryContext, EVContext, SizingContext]


def build_trade_context_snapshot(
    *,
    ctx: ContextType,
    bar_input: Mapping[str, Any],
) -> TradeContextSnapshot:
    snapshot = TradeContextSnapshot(
        session=ctx.session,
        rv_band=ctx.rv_band,
        spread_band=ctx.spread_band,
        or_atr_ratio=ctx.or_atr_ratio,
        min_or_atr_ratio=ctx.min_or_atr_ratio,
        expected_slip_pip=ctx.expected_slip_pip,
        cost_base=ctx.base_cost_pips,
        pip_value=ctx.pip_value,
    )
    if isinstance(ctx, EVContext):
        snapshot.ev_lcb = ctx.ev_lcb
        snapshot.threshold_lcb = ctx.threshold_lcb
        snapshot.ev_pass = ctx.ev_pass
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
        entry_ctx = features.entry_ctx
        if entry_ctx is None:
            raise ValueError("Feature bundle did not include an entry context")
        pending_side, _, _ = self._runner._extract_pending_fields(pending)
        gate_allowed, gate_reason = self._runner._call_strategy_gate(
            entry_ctx,
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
                allow_low_rv=entry_ctx.allow_low_rv,
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
        if not pass_gates(entry_ctx.to_mapping()):
            self._runner.debug_counts["gate_block"] += 1
            self._runner._increment_daily("gate_block")
            metadata = {
                "rv_band": entry_ctx.rv_band,
                "spread_band": entry_ctx.spread_band,
                "or_atr_ratio": entry_ctx.or_atr_ratio,
            }
            self._runner._append_debug_record(
                "gate_block",
                ts=self._runner._last_timestamp,
                side=pending_side,
                rv_band=entry_ctx.rv_band,
                spread_band=entry_ctx.spread_band,
                or_atr_ratio=entry_ctx.or_atr_ratio,
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
            context=entry_ctx,
            pending_side=pending_side,
        )


class EVGate:
    def __init__(self, runner: "BacktestRunner") -> None:
        self._runner = runner

    def evaluate(
        self,
        *,
        ctx: EntryContext,
        pending: Any,
        calibrating: bool,
        timestamp: Optional[str],
    ) -> EVEvaluation:
        pending_side, tp_pips, sl_pips = self._runner._extract_pending_fields(pending)
        ev_key = ctx.ev_key
        ev_mgr = ctx.ev_manager
        ev_mode_value = str(ctx.ev_mode).lower()
        if ev_mode_value == "off":
            threshold_lcb = float("-inf")
        else:
            threshold_lcb = self._runner._call_ev_threshold(
                ctx,
                pending,
                self._runner.rcfg.threshold_lcb_pip,
                ts=timestamp,
                side=pending_side,
            )
        ctx.threshold_lcb_pip = threshold_lcb
        ev_lcb = (
            ev_mgr.ev_lcb_oco(
                float(tp_pips),
                float(sl_pips),
                ctx.cost_pips,
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
                    cost_pips=ctx.cost_pips,
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
                    cost_pips=ctx.cost_pips,
                    tp_pips=tp_pips,
                    sl_pips=sl_pips,
                )
                ev_ctx = EVContext.from_entry(ctx)
                ev_ctx.threshold_lcb_pip = threshold_lcb
                ev_ctx.threshold_lcb = threshold_lcb
                ev_ctx.ev_lcb = ev_lcb
                ev_ctx.ev_pass = False
                ev_ctx.bypass = False
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
                    context=ev_ctx,
                )
        else:
            self._runner._increment_daily("ev_pass")
        ev_ctx = EVContext.from_entry(ctx)
        ev_ctx.threshold_lcb_pip = threshold_lcb
        ev_ctx.threshold_lcb = threshold_lcb
        ev_ctx.ev_lcb = ev_lcb
        ev_ctx.ev_pass = not ev_bypass
        ev_ctx.bypass = ev_bypass
        return EVEvaluation(
            outcome=GateCheckOutcome(passed=True),
            manager=ev_mgr,
            ev_lcb=ev_lcb,
            threshold_lcb=threshold_lcb,
            bypass=ev_bypass,
            context=ev_ctx,
        )


class SizingGate:
    def __init__(self, runner: "BacktestRunner") -> None:
        self._runner = runner

    def evaluate(
        self,
        *,
        ctx: EVContext,
        pending: Any,
        ev_result: EVEvaluation,
        calibrating: bool,
        timestamp: Optional[str],
    ) -> SizingEvaluation:
        sizing_ctx = SizingContext.from_ev(ctx)
        pending_side, tp_pips, sl_pips = self._runner._extract_pending_fields(pending)
        slip_cap = sizing_ctx.slip_cap_pip
        expected_slip = sizing_ctx.expected_slip_pip
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
                ),
                context=sizing_ctx,
            )
        if (
            not ev_result.bypass
            and not calibrating
            and tp_pips is not None
            and sl_pips is not None
        ):
            ctx_for_sizing = sizing_ctx.to_mapping()
            ctx_for_sizing.setdefault("equity", self._runner._equity_live)
            manager = ev_result.manager or sizing_ctx.ev_manager
            if manager is None:
                raise ValueError("EV manager is required when sizing evaluation runs")
            qty_dbg = compute_qty_from_ctx(
                ctx_for_sizing,
                float(sl_pips),
                mode="production",
                tp_pips=float(tp_pips),
                p_lcb=manager.p_lcb(),
            )
            sizing_ctx.qty = qty_dbg
            if qty_dbg <= 0:
                self._runner.debug_counts["zero_qty"] += 1
                return SizingEvaluation(
                    outcome=GateCheckOutcome(
                        passed=False,
                        reason="zero_qty",
                        metadata={"qty": qty_dbg},
                    ),
                    context=sizing_ctx,
                )
        return SizingEvaluation(
            outcome=GateCheckOutcome(passed=True),
            context=sizing_ctx,
        )
