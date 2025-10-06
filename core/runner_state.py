from __future__ import annotations

import copy
from dataclasses import dataclass, field, replace
from typing import Any, Dict, Mapping, Optional, Type, Union

from core.runner_entry import TradeContextSnapshot


@dataclass
class PositionState:
    side: str
    entry_px: float
    tp_px: float
    sl_px: float
    trail_pips: float = 0.0
    qty: float = 1.0
    tp_pips: Optional[float] = None
    sl_pips: Optional[float] = None
    hh: Optional[float] = None
    ll: Optional[float] = None
    hold: int = 0
    entry_ts: Optional[str] = None
    ev_key: Optional[Any] = None
    expected_slip_pip: float = 0.0
    entry_slip_pip: float = 0.0
    ctx_snapshot: Any = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.entry_px = float(self.entry_px)
        self.tp_px = float(self.tp_px)
        self.sl_px = float(self.sl_px)
        self.trail_pips = float(self.trail_pips or 0.0)
        self.qty = float(self.qty or 0.0) if self.qty is not None else 0.0
        if self.tp_pips is not None:
            self.tp_pips = float(self.tp_pips)
        if self.sl_pips is not None:
            self.sl_pips = float(self.sl_pips)
        if self.hh is not None:
            self.hh = float(self.hh)
        if self.ll is not None:
            self.ll = float(self.ll)
        self.hold = int(self.hold or 0)
        self.expected_slip_pip = float(self.expected_slip_pip or 0.0)
        self.entry_slip_pip = float(self.entry_slip_pip or 0.0)
        if self.ctx_snapshot is None:
            self.ctx_snapshot = {}
        elif hasattr(self.ctx_snapshot, "as_dict"):
            # Preserve structured snapshots (e.g. TradeContextSnapshot)
            # without coercing them back into plain dictionaries.
            self.ctx_snapshot = self.ctx_snapshot
        elif not isinstance(self.ctx_snapshot, dict):
            self.ctx_snapshot = dict(self.ctx_snapshot)

    def apply_trailing_stop(self, *, high: float, low: float, pip_size: float) -> PositionState:
        if self.trail_pips <= 0.0:
            return self
        if self.side == "BUY":
            current_hh = self.entry_px if self.hh is None else self.hh
            new_hh = max(current_hh, float(high))
            new_sl = max(self.sl_px, new_hh - self.trail_pips * pip_size)
            return replace(self, hh=new_hh, sl_px=new_sl)
        current_ll = self.entry_px if self.ll is None else self.ll
        new_ll = min(current_ll, float(low))
        new_sl = min(self.sl_px, new_ll + self.trail_pips * pip_size)
        return replace(self, ll=new_ll, sl_px=new_sl)

    def increment_hold(self) -> PositionState:
        return replace(self, hold=self.hold + 1)

    def as_dict(self) -> Dict[str, Any]:
        snapshot = self.ctx_snapshot
        if hasattr(snapshot, "as_dict"):
            snapshot_dict = snapshot.as_dict()
        else:
            snapshot_dict = copy.deepcopy(snapshot)

        data = {
            "side": self.side,
            "entry_px": self.entry_px,
            "tp_px": self.tp_px,
            "sl_px": self.sl_px,
            "trail_pips": self.trail_pips,
            "qty": self.qty,
            "tp_pips": self.tp_pips,
            "sl_pips": self.sl_pips,
            "hh": self.hh,
            "ll": self.ll,
            "hold": self.hold,
            "entry_ts": self.entry_ts,
            "ev_key": self.ev_key,
            "expected_slip_pip": self.expected_slip_pip,
            "entry_slip_pip": self.entry_slip_pip,
            "ctx_snapshot": snapshot_dict,
        }
        return data

    @classmethod
    def from_dict(cls: Type["PositionState"], payload: Mapping[str, Any]) -> PositionState:
        if not isinstance(payload, Mapping):
            raise TypeError("PositionState.from_dict expects a mapping")
        ctx_snapshot = payload.get("ctx_snapshot") or {}
        if not isinstance(ctx_snapshot, Mapping):
            ctx_snapshot = dict(ctx_snapshot)
        else:
            ctx_snapshot = dict(ctx_snapshot)
        return cls(
            side=str(payload.get("side")),
            entry_px=float(payload.get("entry_px")),
            tp_px=float(payload.get("tp_px")),
            sl_px=float(payload.get("sl_px")),
            trail_pips=float(payload.get("trail_pips", 0.0) or 0.0),
            qty=float(payload.get("qty", 1.0) or 0.0),
            tp_pips=(
                float(payload["tp_pips"]) if payload.get("tp_pips") is not None else None
            ),
            sl_pips=(
                float(payload["sl_pips"]) if payload.get("sl_pips") is not None else None
            ),
            hh=float(payload["hh"]) if payload.get("hh") is not None else None,
            ll=float(payload["ll"]) if payload.get("ll") is not None else None,
            hold=int(payload.get("hold", 0) or 0),
            entry_ts=payload.get("entry_ts"),
            ev_key=payload.get("ev_key"),
            expected_slip_pip=float(payload.get("expected_slip_pip", 0.0) or 0.0),
            entry_slip_pip=float(payload.get("entry_slip_pip", 0.0) or 0.0),
            ctx_snapshot=ctx_snapshot,
        )


def _coerce_trade_ctx(
    value: Optional[Mapping[str, Any] | TradeContextSnapshot | Any],
) -> TradeContextSnapshot:
    if isinstance(value, TradeContextSnapshot):
        return value
    if value is None:
        return TradeContextSnapshot()
    if hasattr(value, "as_dict"):
        try:
            return TradeContextSnapshot(**value.as_dict())  # type: ignore[arg-type]
        except Exception:
            return TradeContextSnapshot()
    if isinstance(value, Mapping):
        return TradeContextSnapshot(**dict(value))
    try:
        return TradeContextSnapshot(**dict(value))  # type: ignore[arg-type]
    except Exception:
        return TradeContextSnapshot()


def snapshot_to_dict(
    value: Union[Mapping[str, Any], TradeContextSnapshot, None]
) -> Dict[str, Any]:
    if isinstance(value, TradeContextSnapshot):
        return value.as_dict()
    if value is None:
        return {}
    if hasattr(value, "as_dict"):
        try:
            return dict(value.as_dict())  # type: ignore[arg-type]
        except Exception:
            return {}
    try:
        return dict(value)
    except Exception:
        return {}


@dataclass
class CalibrationPositionState(PositionState):
    ctx_snapshot: Optional[TradeContextSnapshot] = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if isinstance(self.ctx_snapshot, dict):
            self.ctx_snapshot = _coerce_trade_ctx(self.ctx_snapshot)
        elif self.ctx_snapshot is not None and not isinstance(
            self.ctx_snapshot, TradeContextSnapshot
        ):
            self.ctx_snapshot = _coerce_trade_ctx(self.ctx_snapshot)

    def ctx_snapshot_dict(self) -> Dict[str, Any]:
        if isinstance(self.ctx_snapshot, TradeContextSnapshot):
            return self.ctx_snapshot.as_dict()
        return {}

    def as_dict(self) -> Dict[str, Any]:
        data = super().as_dict()
        if isinstance(self.ctx_snapshot, TradeContextSnapshot):
            data["ctx_snapshot"] = self.ctx_snapshot.as_dict()
        elif not data.get("ctx_snapshot"):
            data["ctx_snapshot"] = {}
        return data

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CalibrationPositionState":
        base = PositionState.from_dict(payload)
        data = base.as_dict()
        snapshot_payload = payload.get("ctx_snapshot") or {}
        snapshot = None
        if snapshot_payload:
            snapshot = _coerce_trade_ctx(snapshot_payload)
        return cls(**{**data, "ctx_snapshot": snapshot})


@dataclass
class ActivePositionState(PositionState):
    ctx_snapshot: TradeContextSnapshot = field(default_factory=TradeContextSnapshot)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.ctx_snapshot = _coerce_trade_ctx(self.ctx_snapshot)

    def ctx_snapshot_dict(self) -> Dict[str, Any]:
        return self.ctx_snapshot.as_dict()

    def as_dict(self) -> Dict[str, Any]:
        data = super().as_dict()
        data["ctx_snapshot"] = self.ctx_snapshot.as_dict()
        return data

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ActivePositionState":
        base = PositionState.from_dict(payload)
        data = base.as_dict()
        snapshot_payload = payload.get("ctx_snapshot") or {}
        snapshot = _coerce_trade_ctx(snapshot_payload)
        return cls(**{**data, "ctx_snapshot": snapshot})

