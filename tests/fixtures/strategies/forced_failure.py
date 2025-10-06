from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional

from core.strategy_api import OrderIntent, Strategy


class DeterministicFailureStrategy(Strategy):
    """Strategy stub that deterministically triggers hook failures.

    The runner still receives a pending signal so that the strategy gate and
    EV threshold hooks are invoked, but both hooks raise exceptions. This lets
    tests assert that the debug counters and records capture the failure path
    without relying on randomness.
    """

    def __init__(self) -> None:
        super().__init__()
        self.cfg: Dict[str, Any] = {}
        self._pending_signal: Dict[str, Any] | None = None

    def on_start(
        self,
        cfg: Dict[str, Any],
        instruments: List[str],
        state_store: Dict[str, Any],
    ) -> None:
        self.cfg = dict(cfg)

    def on_bar(self, bar: Dict[str, Any]) -> None:
        # Always expose a BUY setup with fixed TP/SL so hooks run each bar.
        self._pending_signal = {
            "side": "BUY",
            "tp_pips": 10.0,
            "sl_pips": 5.0,
        }

    def signals(self, ctx: Optional[Mapping[str, Any]] = None) -> Iterable[OrderIntent]:
        if ctx is not None:
            self.update_context(ctx)
        # Emit a deterministic intent so downstream sizing/fill paths remain stable.
        self._pending_signal = None
        return [
            OrderIntent(
                side="BUY",
                qty=1.0,
                price=150.0,
                oco={"tp_pips": 10.0, "sl_pips": 5.0, "trail_pips": 0.0},
            )
        ]

    def strategy_gate(self, ctx: Dict[str, Any], pending: Dict[str, Any]) -> bool:
        raise RuntimeError("forced strategy gate failure")

    def ev_threshold(
        self,
        ctx: Dict[str, Any],
        pending: Dict[str, Any],
        base_threshold: float,
    ) -> float:
        raise RuntimeError("forced ev threshold failure")
