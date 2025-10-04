"""
Tokyo micro mean reversion scalping strategy.

This concrete implementation extends :class:`ScalpingTemplate` and populates
`_maybe_build_signal` with z-score based contrarian logic tailored for the
Tokyo session's tight spreads. It illustrates how to build on the shared
scalping template while keeping configuration-driven behaviour.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from .scalping_template import ScalpingTemplate


class TokyoMicroMeanReversion(ScalpingTemplate):
    """Contrarian scalping strategy targeting Tokyo microstructure."""

    api_version = "1.0"

    def _maybe_build_signal(self, bar: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        zscore = float(bar.get("micro_zscore", 0.0) or 0.0)
        threshold = float(self.cfg.get("zscore_threshold", 1.8))
        if abs(zscore) < threshold:
            return None

        entry = bar.get("mid_price") or bar.get("c")
        if entry is None:
            return None

        slope = float(bar.get("micro_trend", 0.0) or 0.0)
        slope_limit = float(self.cfg.get("trend_filter", 0.4))
        if slope_limit > 0 and abs(slope) > slope_limit:
            return None

        override_tp = float(self.cfg.get("atr_tp_mult", 0.4))
        override_sl = float(self.cfg.get("atr_sl_mult", 0.7))
        atr = float(bar.get("atr14", 0.0) or 0.0)
        tp_override = override_tp * atr if atr > 0 else self.cfg.get("default_tp_pips")
        sl_override = override_sl * atr if atr > 0 else self.cfg.get("default_sl_pips")

        side = "SELL" if zscore > 0 else "BUY"
        signal = {
            "side": side,
            "entry": entry,
            "tp_pips": tp_override,
            "sl_pips": sl_override,
            "zscore": zscore,
            "micro_trend": slope,
        }
        return signal


__all__ = ["TokyoMicroMeanReversion"]
