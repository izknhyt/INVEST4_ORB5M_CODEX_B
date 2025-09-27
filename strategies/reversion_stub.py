"""Mean-reversion strategy stub for testing shared gating infrastructure."""
from __future__ import annotations
from typing import Dict, Any, Iterable, Optional, List

from core.strategy_api import Strategy, OrderIntent


class MeanReversionStrategy(Strategy):
    api_version = "1.0"

    def on_start(self, cfg: Dict[str, Any], instruments: List[str], state_store: Dict[str, Any]) -> None:
        self.cfg = cfg
        self.symbol = instruments[0] if instruments else ""
        self._pending_signal: Optional[Dict[str, Any]] = None

    def on_bar(self, bar: Dict[str, Any]) -> None:
        # Minimal placeholder logic: emit alternating BUY/SELL signals when zscore crosses threshold
        zscore = bar.get("zscore", 0.0)
        threshold = float(self.cfg.get("zscore_threshold", 2.0))
        if zscore > threshold:
            self._pending_signal = {"side": "SELL", "entry": bar["c"], "tp_pips": 20.0, "sl_pips": 30.0}
        elif zscore < -threshold:
            self._pending_signal = {"side": "BUY", "entry": bar["c"], "tp_pips": 20.0, "sl_pips": 30.0}
        else:
            self._pending_signal = None

    def strategy_gate(self, ctx: Dict[str, Any], pending: Dict[str, Any]) -> bool:
        # Example: require RVがlowのときはトレード許可、highではスキップ（逆張り想定）
        rv_band = ctx.get("rv_band")
        allow_high = self.cfg.get("allow_high_rv", False)
        if rv_band == "high" and not allow_high:
            return False
        return True

    def ev_threshold(self, ctx: Dict[str, Any], pending: Dict[str, Any], base_threshold: float) -> float:
        # Example: mean reversion prefers lower threshold in low RV session, higher in high RV
        rv_band = ctx.get("rv_band")
        if rv_band == "low":
            return max(0.0, base_threshold - 0.1)
        if rv_band == "high":
            return base_threshold + 0.1
        return base_threshold

    def signals(self) -> Iterable[OrderIntent]:
        if not self._pending_signal:
            return []
        sig = self._pending_signal
        self._pending_signal = None
        return [OrderIntent(sig["side"], qty=1.0, price=sig["entry"], tif="IOC",
                             oco={"tp_pips": sig["tp_pips"], "sl_pips": sig["sl_pips"], "trail_pips": 0.0})]
