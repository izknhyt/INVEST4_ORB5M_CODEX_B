"""
Template scaffolding for intraday (day timeframe) strategies.

This mirrors :mod:`strategies.scalping_template` but assumes lower trade
frequency and wider holding windows. Teams can extend this class when
experimenting with new day-trade ideas without re-implementing boilerplate
for router gating / sizing integration.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Mapping

from core.sizing import compute_qty_from_ctx
from core.strategy_api import OrderIntent, Strategy
from router.router_v0 import pass_gates


class DayStrategyTemplate(Strategy):
    """Skeleton logic for day-trade style strategies."""

    api_version = "1.0"

    def on_start(self, cfg: Dict[str, Any], instruments, state_store) -> None:
        self.cfg = cfg
        self.symbol = instruments[0] if instruments else ""
        self.state: Dict[str, Any] = {
            "bar_idx": 0,
            "last_signal_bar": -10**9,
        }
        self._pending_signal: Optional[Dict[str, Any]] = None

    def on_bar(self, bar: Dict[str, Any]) -> None:
        self.state["bar_idx"] += 1
        self._pending_signal = self._maybe_build_signal(bar)

    # ------------------------------------------------------------------ customization hooks
    def _maybe_build_signal(self, bar: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Return a signal dict or ``None``.

        Override in concrete strategies; the default implementation is a no-op
        so this template can be wired into runners without causing trades.
        """

        return None

    def _apply_signal_defaults(self, signal: Dict[str, Any]) -> Dict[str, Any]:
        defaults = {
            "tif": "IOC",
            "tag": f"{self.__class__.__name__}",
            "tp_pips": float(self.cfg.get("default_tp_pips", 12.0)),
            "sl_pips": float(self.cfg.get("default_sl_pips", 18.0)),
            "trail_pips": float(self.cfg.get("default_trail_pips", 0.0)),
        }
        enriched = defaults | signal
        enriched["side"] = enriched.get("side", "BUY").upper()
        return enriched

    def _post_emit(self, intent: OrderIntent) -> None:
        self.state["last_signal_bar"] = self.state["bar_idx"]

    # ------------------------------------------------------------------ Strategy API
    def signals(self, ctx: Optional[Mapping[str, Any]] = None) -> Iterable[OrderIntent]:
        if not self._pending_signal:
            return []
        ctx_data = self.resolve_runtime_context(ctx)
        if not pass_gates(ctx_data):
            return []

        cooldown = int(ctx_data.get("cooldown_bars", self.cfg.get("cooldown_bars", 4)))
        if cooldown > 0 and (self.state["bar_idx"] - self.state["last_signal_bar"] < cooldown):
            return []

        signal = self._apply_signal_defaults(dict(self._pending_signal))
        sl_pips = max(0.1, float(signal.get("sl_pips", self.cfg.get("default_sl_pips", 18.0))))
        qty = compute_qty_from_ctx(ctx_data, sl_pips)
        if qty <= 0:
            return []

        intent = OrderIntent(
            signal["side"],
            qty=qty,
            price=signal.get("entry"),
            tif=signal.get("tif", "IOC"),
            tag=signal.get("tag"),
            oco={
                "tp_pips": float(signal.get("tp_pips", 0.0)),
                "sl_pips": sl_pips,
                "trail_pips": float(signal.get("trail_pips", 0.0)),
            },
        )
        self._post_emit(intent)
        return [intent]


__all__ = ["DayStrategyTemplate"]
