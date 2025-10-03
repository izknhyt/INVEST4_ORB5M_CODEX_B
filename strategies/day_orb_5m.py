"""
Day ORB 5m v1 (skeleton) — Design v1.1 / ADR-012..025
"""
from __future__ import annotations
from typing import Dict, Any, Iterable, Optional, List
from core.strategy_api import Strategy, OrderIntent
from router.router_v0 import pass_gates
from core.sizing import (
    SizingConfig,
    base_units,
    kelly_multiplier_oco,
    apply_guards,
)
from core.pips import pip_size

class DayORB5m(Strategy):
    api_version = "1.0"
    def on_start(self, cfg: Dict[str,Any], instruments: List[str], state_store: Dict[str,Any]) -> None:
        self.cfg = cfg
        self.state = {
            "or_h": None,
            "or_l": None,
            "in_or_window": True,
            "bar_idx": 0,
            "last_signal_bar": -10**9,
            "broken": False,
            "waiting_retest": False,
            "retest_seen": False,
            "retest_deadline": 0,
            "retest_direction": None,
        }
        self._pending_signal: Optional[Dict[str,Any]] = None
        self._last_gate_reason: Optional[Dict[str, Any]] = None
        self.symbol = instruments[0] if instruments else ""
        self._pip = pip_size(self.symbol) if self.symbol else 0.0001

    def _update_or(self, bars: List[Dict[str,Any]], n: int = 6):
        if len(bars) < n: 
            self.state["in_or_window"] = True
            return
        if self.state["in_or_window"]:
            win = bars[:n]
            self.state["or_h"] = max(b["h"] for b in win)
            self.state["or_l"] = min(b["l"] for b in win)
            self.state["in_or_window"] = False

    def on_bar(self, bar: Dict[str,Any]) -> None:
        # Expect external provides recent window bars list in bar["window"]
        # Reset OR window at new session/day boundary
        if bar.get("new_session"):
            self.state["or_h"] = None
            self.state["or_l"] = None
            self.state["in_or_window"] = True
            self.state["broken"] = False
            self.state["waiting_retest"] = False
            self.state["retest_seen"] = False
            self.state["retest_direction"] = None
        self.state["bar_idx"] += 1
        window = bar.get("window", [])
        self._update_or(window, n=self.cfg.get("or_n", 6))
        or_h, or_l = self.state["or_h"], self.state["or_l"]
        self._pending_signal = None
        if or_h is None or or_l is None: 
            return
        k_tp = self.cfg.get("k_tp", 1.0)
        k_sl = self.cfg.get("k_sl", 0.8)
        k_tr = self.cfg.get("k_tr", 0.0)
        atr14 = bar.get("atr14", 0.0)
        # Convert ATR from price units to pips
        atr_pips = (atr14 / self._pip) if self._pip else 0.0
        tp_pips = k_tp * atr_pips
        sl_pips = k_sl * atr_pips
        trail_pips = k_tr * atr_pips if k_tr>0 else 0.0
        require_close = self.cfg.get("require_close_breakout", False)
        require_retest = self.cfg.get("require_retest", False)
        retest_max = int(self.cfg.get("retest_max_bars", 6))
        tol_k = float(self.cfg.get("retest_tol_k", 0.25))
        tol_price = tol_k * atr_pips * self._pip

        if not self.state.get("broken"):
            if require_retest:
                # Step1: detect first touch (initial breakout), then wait for retest
                if not self.state["waiting_retest"] and not self.state["retest_seen"]:
                    hit_buy = bar["h"] >= or_h
                    hit_sell = bar["l"] <= or_l
                    direction: Optional[str] = None
                    if hit_buy and not hit_sell:
                        direction = "buy"
                    elif hit_sell and not hit_buy:
                        direction = "sell"
                    elif hit_buy and hit_sell:
                        close = bar.get("c")
                        if close is not None:
                            if close >= or_h and close >= or_l:
                                direction = "buy"
                            elif close <= or_l and close <= or_h:
                                direction = "sell"
                        if direction is None:
                            distance_up = bar["h"] - or_h
                            distance_down = or_l - bar["l"]
                            direction = "buy" if distance_up >= distance_down else "sell"
                    if direction:
                        # first breakout seen; set waiting retest
                        self.state["waiting_retest"] = True
                        self.state["retest_deadline"] = self.state["bar_idx"] + retest_max
                        self.state["retest_direction"] = direction
                else:
                    # While waiting for retest / after retest seen
                    if self.state["waiting_retest"] and not self.state["retest_seen"]:
                        # check retest toward OR line
                        direction = self.state.get("retest_direction")
                        retest_match = False
                        if direction == "buy":
                            retest_match = bar["l"] <= or_h + tol_price
                        elif direction == "sell":
                            retest_match = bar["h"] >= or_l - tol_price
                        else:
                            retest_match = (bar["l"] <= or_h + tol_price) or (bar["h"] >= or_l - tol_price)
                        if retest_match:
                            self.state["retest_seen"] = True
                            self.state["waiting_retest"] = False
                        elif self.state["bar_idx"] >= self.state["retest_deadline"]:
                            # expire this session (skip trade)
                            self.state["broken"] = True
                            self.state["waiting_retest"] = False
                            self.state["retest_direction"] = None
                    elif self.state["retest_seen"]:
                        # require re-break with optional close filter
                        direction = self.state.get("retest_direction")
                        if direction == "buy" and (bar["h"] >= or_h) and ((not require_close) or (bar["c"] >= or_h)):
                            self._pending_signal = {"side":"BUY","tp_pips":tp_pips,"sl_pips":sl_pips,"trail_pips":trail_pips,"entry":or_h}
                            self.state["retest_direction"] = None
                        elif direction == "sell" and (bar["l"] <= or_l) and ((not require_close) or (bar["c"] <= or_l)):
                            self._pending_signal = {"side":"SELL","tp_pips":tp_pips,"sl_pips":sl_pips,"trail_pips":trail_pips,"entry":or_l}
                            self.state["retest_direction"] = None
            else:
                if (bar["h"] >= or_h) and ((not require_close) or (bar["c"] >= or_h)):
                    self._pending_signal = {"side":"BUY","tp_pips":tp_pips,"sl_pips":sl_pips,"trail_pips":trail_pips,"entry":or_h}
                elif (bar["l"] <= or_l) and ((not require_close) or (bar["c"] <= or_l)):
                    self._pending_signal = {"side":"SELL","tp_pips":tp_pips,"sl_pips":sl_pips,"trail_pips":trail_pips,"entry":or_l}

    def signals(self) -> Iterable[OrderIntent]:
        if not self._pending_signal:
            return []
        # Context should include router gates + EV + sizing related configs
        ctx = self.cfg.get("ctx", {}).copy()
        # Simple cooldown by bars
        cooldown = int(ctx.get("cooldown_bars", self.cfg.get("cooldown_bars", 0)))
        if cooldown > 0 and (self.state["bar_idx"] - self.state["last_signal_bar"] < cooldown):
            return []
        if not pass_gates(ctx):
            return []
        sig = self._pending_signal

        # Calibration mode: bypass EV sizing and emit minimal intent for fill simulation
        if ctx.get("calibrating") or ctx.get("ev_mode") == "off":
            tag = f"day_orb5m#{sig['side']}#calib"
            # size: base * size_floor_mult when ev_mode=='off', else 1.0 (ignored downstream in calib)
            qty = 1.0
            if ctx.get("ev_mode") == "off":
                from core.sizing import SizingConfig as _SZ, base_units as _BU, apply_guards as _AG
                sz_cfg = _SZ()
                equity = float(ctx.get("equity", 0.0))
                pip_value = float(ctx.get("pip_value", 0.0))
                base = _BU(equity, pip_value, sig["sl_pips"], sz_cfg)
                qty = _AG(base * float(ctx.get("size_floor_mult", 0.01)), equity, pip_value, sig["sl_pips"], sz_cfg)
            return [OrderIntent(sig["side"], qty=qty, price=sig["entry"], tif="IOC", tag=tag,
                                oco={"tp_pips":sig["tp_pips"], "sl_pips":sig["sl_pips"], "trail_pips":sig["trail_pips"]})]

        # Warmup path: bypass EV and use minimal fixed multiplier to bootstrap statistics
        warmup_left = int(ctx.get("warmup_left", 0))
        if warmup_left > 0:
            equity = float(ctx.get("equity", 0.0))
            pip_value = float(ctx.get("pip_value", 0.0))
            sizing_cfg_dict = ctx.get("sizing_cfg", {})
            sz_cfg = SizingConfig(
                risk_per_trade_pct=sizing_cfg_dict.get("risk_per_trade_pct", 0.25),
                kelly_fraction=sizing_cfg_dict.get("kelly_fraction", 0.25),
                units_cap=sizing_cfg_dict.get("units_cap", 5.0),
                max_trade_loss_pct=sizing_cfg_dict.get("max_trade_loss_pct", 0.5),
            )
            base = base_units(equity, pip_value, sig["sl_pips"], sz_cfg)
            warm_mult = float(ctx.get("warmup_mult", 0.05))  # 5% of base as minimal size
            qty = apply_guards(base * max(0.0, warm_mult), equity, pip_value, sig["sl_pips"], sz_cfg)
            if qty <= 0:
                return []
            tag = f"day_orb5m#{sig['side']}#warmup"
            return [OrderIntent(sig["side"], qty=qty, price=sig["entry"], tif="IOC", tag=tag,
                                oco={"tp_pips":sig["tp_pips"], "sl_pips":sig["sl_pips"], "trail_pips":sig["trail_pips"]})]

        # EV gate (Beta-Binomial for OCO)
        ev = ctx.get("ev_oco")  # expected: instance of BetaBinomialEV
        cost_pips = float(ctx.get("cost_pips", 0.0))
        threshold = float(ctx.get("threshold_lcb_pip", 0.5))
        ev_lcb = None
        p_lcb = None
        if ev is not None:
            mode = ctx.get("ev_mode", "lcb")
            if mode == "mean":
                p_lcb = getattr(ev, 'p_mean')()
                ev_lcb = p_lcb*sig["tp_pips"] - (1.0-p_lcb)*sig["sl_pips"] - cost_pips
            else:
                ev_lcb = ev.ev_lcb_oco(sig["tp_pips"], sig["sl_pips"], cost_pips)
                p_lcb = ev.p_lcb()
        else:
            # If EV estimator is missing, act conservatively: no trade
            return []

        if ctx.get("ev_mode", "lcb") == "lcb" and (ev_lcb is None or ev_lcb < threshold):
            return []

        # Position sizing
        equity = float(ctx.get("equity", 0.0))
        pip_value = float(ctx.get("pip_value", 0.0))
        sizing_cfg_dict = ctx.get("sizing_cfg", {})
        sz_cfg = SizingConfig(
            risk_per_trade_pct=sizing_cfg_dict.get("risk_per_trade_pct", 0.25),
            kelly_fraction=sizing_cfg_dict.get("kelly_fraction", 0.25),
            units_cap=sizing_cfg_dict.get("units_cap", 5.0),
            max_trade_loss_pct=sizing_cfg_dict.get("max_trade_loss_pct", 0.5),
        )
        base = base_units(equity, pip_value, sig["sl_pips"], sz_cfg)
        mult = kelly_multiplier_oco(p_lcb or 0.0, sig["tp_pips"], sig["sl_pips"], sz_cfg)
        qty = apply_guards(base * mult, equity, pip_value, sig["sl_pips"], sz_cfg)

        if qty <= 0:
            return []

        tag = f"day_orb5m#{sig['side']}"
        self.state["last_signal_bar"] = self.state["bar_idx"]
        self.state["broken"] = True  # block re-entry until next session reset
        return [OrderIntent(sig["side"], qty=qty, price=sig["entry"], tif="IOC", tag=tag,
                            oco={"tp_pips":sig["tp_pips"], "sl_pips":sig["sl_pips"], "trail_pips":sig["trail_pips"]})]

    def strategy_gate(self, ctx: Dict[str, Any], pending: Dict[str, Any]) -> bool:
        """戦略固有のゲート判定（OR/ATR、RVバンドなど）。"""
        self._last_gate_reason = None
        min_or = self.cfg.get("min_or_atr_ratio", ctx.get("min_or_atr_ratio", 0.0))
        or_ratio = ctx.get("or_atr_ratio", 0.0)
        if min_or and or_ratio < min_or:
            self._last_gate_reason = {
                "stage": "or_filter",
                "or_atr_ratio": or_ratio,
                "min_or_atr_ratio": min_or,
            }
            return False

        allow_low = ctx.get("allow_low_rv", False)
        rv_band = ctx.get("rv_band")
        if not allow_low and rv_band not in ("mid", "high"):
            self._last_gate_reason = {
                "stage": "rv_filter",
                "rv_band": rv_band,
            }
            return False

        return True

    def ev_threshold(self, ctx: Dict[str, Any], pending: Dict[str, Any], base_threshold: float) -> float:
        """シグナルの質に応じて EV 閾値を調整する。"""
        min_or = self.cfg.get("min_or_atr_ratio", ctx.get("min_or_atr_ratio", 0.0)) or 0.0
        or_ratio = ctx.get("or_atr_ratio", 0.0)
        boost = max(0.0, float(self.cfg.get("ev_threshold_boost", 0.1)))
        relief = max(0.0, float(self.cfg.get("ev_threshold_relief", 0.1)))

        threshold = base_threshold
        if min_or and or_ratio >= min_or * 1.5:
            threshold = max(0.0, base_threshold - relief)
        elif min_or and or_ratio < min_or + 0.05:
            threshold = base_threshold + boost

        profile = ctx.get("ev_profile_stats")
        stats = None
        if isinstance(profile, dict):
            recent = profile.get("recent") or {}
            long_term = profile.get("long_term") or {}
            if recent.get("observations"):
                stats = recent
                stats_weight = 1.0
            elif long_term.get("observations"):
                stats = long_term
                stats_weight = 0.5
            else:
                stats = None
                stats_weight = 0.0
        else:
            stats_weight = 0.0

        if stats and stats_weight > 0.0:
            try:
                p_mean = float(stats.get("p_mean", 0.0))
                obs = float(stats.get("observations", 0.0))
                tp = float(pending.get("tp_pips", 0.0))
                sl = float(pending.get("sl_pips", 0.0))
                cost = float(ctx.get("cost_pips", 0.0))
            except (TypeError, ValueError):
                p_mean = 0.0
                obs = 0.0

            if p_mean > 0.0 and (tp + sl) > 0.0:
                expected = p_mean * tp - (1.0 - p_mean) * sl - cost
                obs_scale = max(5.0, float(self.cfg.get("ev_profile_obs_norm", 15.0)))
                confidence = min(1.0, max(0.0, obs / obs_scale)) * stats_weight
                delta = expected - base_threshold
                max_down = base_threshold if base_threshold > 0.0 else 0.5
                max_up = max(base_threshold, 0.5) + 0.5
                adjust = confidence * delta
                if adjust > max_down:
                    adjust = max_down
                elif adjust < -max_up:
                    adjust = -max_up
                threshold = max(0.0, threshold - adjust)

        return threshold
