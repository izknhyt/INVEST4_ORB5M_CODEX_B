"""Mean reversion strategy implementation for the shared gating/EV pipeline."""
from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional

from core.pips import pip_size
from core.sizing import compute_qty_from_ctx
from core.strategy_api import OrderIntent, Strategy
from router.router_v0 import pass_gates


class MeanReversionStrategy(Strategy):
    """Contrarian strategy that fades large z-score excursions."""

    api_version = "1.0"

    def on_start(self, cfg: Dict[str, Any], instruments: List[str], state_store: Dict[str, Any]) -> None:
        self.cfg = cfg
        self.symbol = instruments[0] if instruments else ""
        self._pip = pip_size(self.symbol) if self.symbol else 0.0001
        self.state: Dict[str, Any] = {
            "bar_idx": 0,
            "last_signal_bar": -10**9,
            "last_zscore": 0.0,
            "last_adx": math.nan,
        }
        self._pending_signal: Optional[Dict[str, Any]] = None
        self._last_gate_reason: Optional[Dict[str, Any]] = None

    def on_bar(self, bar: Dict[str, Any]) -> None:
        self.state["bar_idx"] += 1
        self._pending_signal = None
        zscore = float(bar.get("zscore", 0.0) or 0.0)
        self.state["last_zscore"] = zscore
        self.state["last_adx"] = float(bar.get("adx14", math.nan))

        threshold = float(self.cfg.get("zscore_threshold", 1.5))
        if abs(zscore) < threshold:
            return

        entry_price = bar.get("c")
        if entry_price is None:
            return

        atr = float(bar.get("atr14", 0.0) or 0.0)
        atr_pips = atr / self._pip if self._pip else 0.0
        if atr_pips <= 0.0:
            atr_pips = float(self.cfg.get("default_atr_pips", 10.0))

        tp_mult = float(self.cfg.get("tp_atr_mult", 0.6))
        sl_mult = float(self.cfg.get("sl_atr_mult", 1.2))
        trail_mult = float(self.cfg.get("trail_atr_mult", 0.0))
        min_tp = float(self.cfg.get("min_tp_pips", 4.0))
        min_sl = float(self.cfg.get("min_sl_pips", 6.0))

        tp_pips = max(min_tp, tp_mult * atr_pips)
        sl_pips = max(min_sl, sl_mult * atr_pips, tp_pips * float(self.cfg.get("sl_over_tp", 1.2)))
        trail_pips = max(0.0, trail_mult * atr_pips)

        side = "SELL" if zscore > 0 else "BUY"
        pending = {
            "side": side,
            "entry": entry_price,
            "tp_pips": tp_pips,
            "sl_pips": sl_pips,
            "trail_pips": trail_pips,
            "zscore": zscore,
        }
        self._pending_signal = pending

    def strategy_gate(self, ctx: Dict[str, Any], pending: Dict[str, Any]) -> bool:
        self._last_gate_reason = None
        rv_band = ctx.get("rv_band")
        if rv_band == "high" and not self.cfg.get("allow_high_rv", False):
            self._last_gate_reason = {"stage": "rv_filter", "rv_band": rv_band}
            return False
        if rv_band == "mid" and not self.cfg.get("allow_mid_rv", True):
            self._last_gate_reason = {"stage": "rv_filter", "rv_band": rv_band}
            return False
        if rv_band == "low" and not self.cfg.get("allow_low_rv", True):
            self._last_gate_reason = {"stage": "rv_filter", "rv_band": rv_band}
            return False

        max_adx = float(self.cfg.get("max_adx", 28.0))
        last_adx = self.state.get("last_adx")
        if math.isfinite(max_adx) and max_adx > 0 and isinstance(last_adx, (int, float)):
            if math.isfinite(last_adx) and last_adx > max_adx:
                self._last_gate_reason = {"stage": "adx_filter", "adx": last_adx, "max_adx": max_adx}
                return False

        cooldown = int(self.cfg.get("cooldown_bars", ctx.get("cooldown_bars", 0)))
        if cooldown > 0 and (self.state["bar_idx"] - self.state["last_signal_bar"] < cooldown):
            self._last_gate_reason = {"stage": "cooldown", "bars_since": self.state["bar_idx"] - self.state["last_signal_bar"]}
            return False

        min_zscore = float(self.cfg.get("min_trend_zscore", 0.0))
        if min_zscore > 0.0 and abs(pending.get("zscore", 0.0)) < min_zscore:
            self._last_gate_reason = {"stage": "zscore_filter", "zscore": pending.get("zscore")}
            return False

        return True

    def ev_threshold(self, ctx: Dict[str, Any], pending: Dict[str, Any], base_threshold: float) -> float:
        zscore = abs(float(pending.get("zscore", 0.0)))
        trigger = float(self.cfg.get("zscore_threshold", 1.5))
        cushion = max(0.5, float(self.cfg.get("zscore_relief_scale", 1.0)))
        stretch = max(0.5, float(self.cfg.get("zscore_penalty_scale", 1.0)))

        threshold = base_threshold
        if trigger > 0.0:
            intensity = max(0.0, zscore - trigger)
            if intensity > 0.0:
                threshold = max(0.0, base_threshold - intensity * cushion * 0.05)
            else:
                threshold = base_threshold + (trigger - zscore) * stretch * 0.05

        profile = ctx.get("ev_profile_stats")
        stats = None
        weight = 0.0
        if isinstance(profile, dict):
            recent = profile.get("recent") or {}
            long_term = profile.get("long_term") or {}
            if recent.get("observations"):
                stats = recent
                weight = 1.0
            elif long_term.get("observations"):
                stats = long_term
                weight = 0.6
        if stats and weight > 0.0:
            try:
                p_mean = float(stats.get("p_mean", 0.0))
                obs = float(stats.get("observations", 0.0))
            except (TypeError, ValueError):
                p_mean = 0.0
                obs = 0.0
            if p_mean > 0.0:
                obs_scale = max(5.0, float(self.cfg.get("ev_profile_obs_norm", 20.0)))
                confidence = min(1.0, max(0.0, obs / obs_scale)) * weight
                tp = float(pending.get("tp_pips", 0.0))
                sl = float(pending.get("sl_pips", 0.0))
                cost = float(ctx.get("cost_pips", 0.0))
                expected = p_mean * tp - (1.0 - p_mean) * sl - cost
                threshold = max(0.0, threshold - confidence * expected)
        return threshold

    def signals(self) -> Iterable[OrderIntent]:
        if not self._pending_signal:
            return []
        ctx = self.get_context()
        if not pass_gates(ctx):
            return []

        sig = self._pending_signal
        cooldown = int(self.cfg.get("cooldown_bars", ctx.get("cooldown_bars", 0)))
        if cooldown > 0 and (self.state["bar_idx"] - self.state["last_signal_bar"] < cooldown):
            return []

        if ctx.get("calibrating") or ctx.get("ev_mode") == "off":
            qty = compute_qty_from_ctx(ctx, sig["sl_pips"], mode="calibration")
            if ctx.get("ev_mode") == "off" and qty <= 0:
                return []
            tag = f"mean_reversion#{sig['side']}#calib"
            self.state["last_signal_bar"] = self.state["bar_idx"]
            return [
                OrderIntent(
                    sig["side"],
                    qty=qty,
                    price=sig["entry"],
                    tif="IOC",
                    tag=tag,
                    oco={"tp_pips": sig["tp_pips"], "sl_pips": sig["sl_pips"], "trail_pips": sig["trail_pips"]},
                )
            ]

        warmup_left = int(ctx.get("warmup_left", 0))
        if warmup_left > 0:
            qty = compute_qty_from_ctx(ctx, sig["sl_pips"], mode="warmup")
            if qty <= 0:
                return []
            tag = f"mean_reversion#{sig['side']}#warmup"
            self.state["last_signal_bar"] = self.state["bar_idx"]
            return [
                OrderIntent(
                    sig["side"],
                    qty=qty,
                    price=sig["entry"],
                    tif="IOC",
                    tag=tag,
                    oco={"tp_pips": sig["tp_pips"], "sl_pips": sig["sl_pips"], "trail_pips": sig["trail_pips"]},
                )
            ]

        ev = ctx.get("ev_oco")
        if ev is None:
            return []
        p_lcb = ev.p_lcb()
        qty = compute_qty_from_ctx(
            ctx,
            sig["sl_pips"],
            mode="production",
            tp_pips=sig["tp_pips"],
            p_lcb=p_lcb,
        )
        if qty <= 0:
            return []

        tag = f"mean_reversion#{sig['side']}"
        self.state["last_signal_bar"] = self.state["bar_idx"]
        return [
            OrderIntent(
                sig["side"],
                qty=qty,
                price=sig["entry"],
                tif="IOC",
                tag=tag,
                oco={"tp_pips": sig["tp_pips"], "sl_pips": sig["sl_pips"], "trail_pips": sig["trail_pips"]},
            )
        ]
