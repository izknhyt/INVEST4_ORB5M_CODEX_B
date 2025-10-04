"""
London/NY momentum continuation day strategy.

Extends :class:`DayStrategyTemplate` to illustrate how to implement a session
follow-through momentum play on top of the shared day-trade skeleton.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from .day_template import DayStrategyTemplate


class SessionMomentumContinuation(DayStrategyTemplate):
    """Momentum continuation strategy for London → New York sessions."""

    api_version = "1.0"

    def _maybe_build_signal(self, bar: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        trend = float(bar.get("trend_score", 0.0) or 0.0)
        pullback = float(bar.get("pullback", 0.0) or 0.0)
        adx = float(bar.get("adx14", 0.0) or 0.0)
        rv_band = (bar.get("rv_band") or "").lower()

        min_trend = float(self.cfg.get("trend_threshold", 0.7))
        max_pullback = float(self.cfg.get("pullback_threshold", 0.45))
        min_adx = float(self.cfg.get("min_adx", 18.0))

        if trend < min_trend or pullback > max_pullback or adx < min_adx:
            return None

        if rv_band not in ("mid", "high"):
            return None

        direction = "BUY" if trend >= 0 else "SELL"
        entry = bar.get("c")
        if entry is None:
            return None

        atr = float(bar.get("atr14", 0.0) or 0.0)
        tp_mult = float(self.cfg.get("atr_tp_mult", 1.2))
        sl_mult = float(self.cfg.get("atr_sl_mult", 1.8))

        return {
            "side": direction,
            "entry": entry,
            "tp_pips": atr * tp_mult if atr > 0 else self.cfg.get("default_tp_pips"),
            "sl_pips": atr * sl_mult if atr > 0 else self.cfg.get("default_sl_pips"),
            "trend": trend,
            "pullback": pullback,
        }


__all__ = ["SessionMomentumContinuation"]
