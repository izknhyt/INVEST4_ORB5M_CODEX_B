"""
Template scaffolding for scalping strategies.

This module provides a minimal Strategy subclass that developers can extend
when prototyping new scalping ideas. The default implementation is
intentionally conservative: it never submits orders unless
`_maybe_build_signal` is overridden to return a populated signal dictionary.

Usage guidelines:
  * Override `_maybe_build_signal` to inspect the incoming bar payload and
    return a dict with the keys shown in `_apply_signal_defaults`.
  * Optional: override `_post_emit` if additional bookkeeping is required
    after a signal has been converted into an OrderIntent.
  * The manifest (`configs/strategies/scalping_template.yaml`) documents
    common configuration knobs (cooldown, default TP / SL multipliers, etc.).
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

from core.sizing import compute_qty_from_ctx
from core.strategy_api import OrderIntent, Strategy
from router.router_v0 import pass_gates


class ScalpingTemplate(Strategy):
    """Skeleton logic for high-frequency scalping strategies."""

    api_version = "1.0"

    def on_start(self, cfg: Dict[str, Any], instruments, state_store) -> None:
        self.cfg = cfg
        self.symbol = instruments[0] if instruments else ""
        self.state: Dict[str, Any] = {
            "bar_idx": 0,
            "last_signal_bar": -10**9,
        }
        self._pending_signal: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------ lifecycle
    def on_bar(self, bar: Dict[str, Any]) -> None:
        self.state["bar_idx"] += 1
        self._pending_signal = self._maybe_build_signal(bar)

    # ------------------------------------------------------------------ template hooks
    def _maybe_build_signal(self, bar: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Return a signal dict or ``None``.

        The default implementation is a no-op so that the template can be wired
        into runners without triggering trades. Override in concrete strategies
        to populate: ``side``, ``entry``, ``tp_pips``, ``sl_pips`` (plus any
        extra metadata consumed by `_apply_signal_defaults`).
        """

        return None

    def _apply_signal_defaults(self, signal: Dict[str, Any]) -> Dict[str, Any]:
        defaults = {
            "tif": "IOC",
            "tag": f"{self.__class__.__name__}",
            "tp_pips": float(self.cfg.get("default_tp_pips", 4.0)),
            "sl_pips": float(self.cfg.get("default_sl_pips", 6.0)),
            "trail_pips": float(self.cfg.get("default_trail_pips", 0.0)),
        }
        enriched = defaults | signal
        enriched["side"] = enriched.get("side", "BUY").upper()
        return enriched

    def _post_emit(self, intent: OrderIntent) -> None:
        """Hook for subclasses to record analytics after emitting a signal."""

        # Default: update cooldown sentinel only.
        self.state["last_signal_bar"] = self.state["bar_idx"]

    # ------------------------------------------------------------------ Strategy API
    def signals(self) -> Iterable[OrderIntent]:
        if not self._pending_signal:
            return []
        ctx = self.get_context()
        if not pass_gates(ctx):
            return []

        cooldown = int(ctx.get("cooldown_bars", self.cfg.get("cooldown_bars", 0)))
        if cooldown > 0 and (self.state["bar_idx"] - self.state["last_signal_bar"] < cooldown):
            return []

        signal = self._apply_signal_defaults(dict(self._pending_signal))
        sl_pips = max(0.1, float(signal.get("sl_pips", self.cfg.get("default_sl_pips", 6.0))))
        qty = compute_qty_from_ctx(ctx, sl_pips)
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


__all__ = ["ScalpingTemplate"]
