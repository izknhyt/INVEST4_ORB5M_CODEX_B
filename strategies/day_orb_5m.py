"""
Day ORB 5m v1 (skeleton) — Design v1.1 / ADR-012..025
"""
from __future__ import annotations
from typing import Dict, Any, Iterable, Optional, List, Mapping
from core.strategy_api import Strategy, OrderIntent
from router.router_v0 import pass_gates
from core.sizing import compute_qty_from_ctx
from core.pips import pip_size

class DayORB5m(Strategy):
    api_version = "1.0"
    def on_start(self, cfg: Dict[str,Any], instruments: List[str], state_store: Dict[str,Any]) -> None:
        self.cfg = dict(cfg)
        self.cfg.setdefault("cooldown_bars", 0)
        self.cfg.setdefault("min_micro_trend", 0.0)
        self.cfg.setdefault("min_atr_pips", 0.0)
        self.cfg.setdefault("max_atr_pips", 0.0)
        self.cfg.setdefault("max_signals_per_day", 0)
        self.cfg.setdefault("fallback_win_rate", 0.55)
        self.cfg.setdefault("max_loss_streak", 0)
        self.cfg.setdefault("max_daily_loss_pips", 0.0)
        self.cfg.setdefault("max_daily_trade_count", 0)
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
            "signals_today": 0,
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
            self.state["signals_today"] = 0
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
                            self._pending_signal = {
                                "side": "BUY",
                                "tp_pips": tp_pips,
                                "sl_pips": sl_pips,
                                "trail_pips": trail_pips,
                                "entry": or_h,
                                "atr_pips": atr_pips,
                                "micro_trend": bar.get("micro_trend"),
                            }
                            self.state["retest_direction"] = None
                        elif direction == "sell" and (bar["l"] <= or_l) and ((not require_close) or (bar["c"] <= or_l)):
                            self._pending_signal = {
                                "side": "SELL",
                                "tp_pips": tp_pips,
                                "sl_pips": sl_pips,
                                "trail_pips": trail_pips,
                                "entry": or_l,
                                "atr_pips": atr_pips,
                                "micro_trend": bar.get("micro_trend"),
                            }
                            self.state["retest_direction"] = None
            else:
                if (bar["h"] >= or_h) and ((not require_close) or (bar["c"] >= or_h)):
                    self._pending_signal = {
                        "side": "BUY",
                        "tp_pips": tp_pips,
                        "sl_pips": sl_pips,
                        "trail_pips": trail_pips,
                        "entry": or_h,
                        "atr_pips": atr_pips,
                        "micro_trend": bar.get("micro_trend"),
                    }
                elif (bar["l"] <= or_l) and ((not require_close) or (bar["c"] <= or_l)):
                    self._pending_signal = {
                        "side": "SELL",
                        "tp_pips": tp_pips,
                        "sl_pips": sl_pips,
                        "trail_pips": trail_pips,
                        "entry": or_l,
                        "atr_pips": atr_pips,
                        "micro_trend": bar.get("micro_trend"),
                    }

    def get_pending_signal(self) -> Optional[Dict[str, Any]]:
        return self._pending_signal

    def signals(self, ctx: Optional[Mapping[str, Any]] = None) -> Iterable[OrderIntent]:
        pending = self.get_pending_signal()
        if not pending:
            return []
        # Context should include router gates + EV + sizing related configs
        ctx_data = self.resolve_runtime_context(ctx)
        self._last_gate_reason = None
        # Simple cooldown by bars
        cooldown = int(ctx_data.get("cooldown_bars", self.cfg.get("cooldown_bars", 0)))
        if cooldown > 0 and (self.state["bar_idx"] - self.state["last_signal_bar"] < cooldown):
            self._last_gate_reason = {
                "stage": "cooldown_guard",
                "bars_since": self.state["bar_idx"] - self.state["last_signal_bar"],
                "cooldown_bars": cooldown,
            }
            return []
        if not pass_gates(ctx_data):
            return []
        sig = pending

        signals_today = self.state.get("signals_today", 0)
        max_signals = int(self.cfg.get("max_signals_per_day", 0) or 0)
        if max_signals and signals_today >= max_signals:
            self._last_gate_reason = {
                "stage": "daily_signal_cap",
                "signals_today": signals_today,
                "max_signals_per_day": max_signals,
            }
            return []

        loss_streak = int(ctx_data.get("loss_streak", 0) or 0)
        max_loss_streak = int(self.cfg.get("max_loss_streak", 0) or 0)
        if max_loss_streak and loss_streak >= max_loss_streak:
            self._last_gate_reason = {
                "stage": "loss_streak_guard",
                "loss_streak": loss_streak,
                "max_loss_streak": max_loss_streak,
            }
            return []

        daily_loss_pips = float(ctx_data.get("daily_loss_pips", 0.0) or 0.0)
        max_daily_loss = float(self.cfg.get("max_daily_loss_pips", 0.0) or 0.0)
        if max_daily_loss > 0:
            cumulative_loss = abs(daily_loss_pips) if daily_loss_pips < 0 else 0.0
            if cumulative_loss >= max_daily_loss:
                self._last_gate_reason = {
                    "stage": "daily_loss_guard",
                    "daily_loss_pips": daily_loss_pips,
                    "max_daily_loss_pips": max_daily_loss,
                }
                return []

        daily_trade_count = int(ctx_data.get("daily_trade_count", 0) or 0)
        max_daily_trades = int(self.cfg.get("max_daily_trade_count", 0) or 0)
        if max_daily_trades and daily_trade_count >= max_daily_trades:
            self._last_gate_reason = {
                "stage": "daily_trade_guard",
                "daily_trade_count": daily_trade_count,
                "max_daily_trade_count": max_daily_trades,
            }
            return []

        atr_pips = sig.get("atr_pips")
        min_atr = float(self.cfg.get("min_atr_pips", 0.0) or 0.0)
        max_atr = float(self.cfg.get("max_atr_pips", 0.0) or 0.0)
        if atr_pips is not None:
            if min_atr and atr_pips < min_atr:
                self._last_gate_reason = {
                    "stage": "atr_filter",
                    "atr_pips": atr_pips,
                    "min_atr_pips": min_atr,
                }
                return []
            if max_atr and atr_pips > max_atr:
                self._last_gate_reason = {
                    "stage": "atr_filter",
                    "atr_pips": atr_pips,
                    "max_atr_pips": max_atr,
                }
                return []

        min_micro = float(self.cfg.get("min_micro_trend", 0.0) or 0.0)
        micro_val = sig.get("micro_trend")
        if min_micro > 0 and micro_val is not None:
            if sig["side"] == "BUY" and micro_val < min_micro:
                self._last_gate_reason = {
                    "stage": "micro_trend_filter",
                    "side": sig["side"],
                    "micro_trend": micro_val,
                    "min_micro_trend": min_micro,
                }
                return []
            if sig["side"] == "SELL" and micro_val > -min_micro:
                self._last_gate_reason = {
                    "stage": "micro_trend_filter",
                    "side": sig["side"],
                    "micro_trend": micro_val,
                    "min_micro_trend": min_micro,
                }
                return []

        # Calibration mode: bypass EV sizing and emit minimal intent for fill simulation
        ev_mode = str(ctx_data.get("ev_mode", "lcb")).lower()
        if ctx_data.get("calibrating"):
            qty = compute_qty_from_ctx(ctx_data, sig["sl_pips"], mode="calibration")
            tag = f"day_orb5m#{sig['side']}#calib"
            self.state["last_signal_bar"] = self.state["bar_idx"]
            self.state["broken"] = True
            self.state["signals_today"] = signals_today + 1
            return [
                OrderIntent(
                    sig["side"],
                    qty=qty,
                    price=sig["entry"],
                    tif="IOC",
                    tag=tag,
                    oco={
                        "tp_pips": sig["tp_pips"],
                        "sl_pips": sig["sl_pips"],
                        "trail_pips": sig["trail_pips"],
                    },
                )
            ]

        # Warmup path: bypass EV and use minimal fixed multiplier to bootstrap statistics
        warmup_left = int(ctx_data.get("warmup_left", 0))
        if warmup_left > 0:
            qty = compute_qty_from_ctx(ctx_data, sig["sl_pips"], mode="warmup")
            if qty <= 0:
                return []
            tag = f"day_orb5m#{sig['side']}#warmup"
            self.state["last_signal_bar"] = self.state["bar_idx"]
            self.state["broken"] = True
            self.state["signals_today"] = signals_today + 1
            return [OrderIntent(sig["side"], qty=qty, price=sig["entry"], tif="IOC", tag=tag,
                                oco={"tp_pips":sig["tp_pips"], "sl_pips":sig["sl_pips"], "trail_pips":sig["trail_pips"]})]

        # EV gate (Beta-Binomial for OCO)
        cost_pips = float(ctx_data.get("cost_pips", 0.0))
        threshold = float(ctx_data.get("threshold_lcb_pip", 0.5))
        ev_lcb = None
        p_lcb = None
        if ev_mode != "off":
            ev = ctx_data.get("ev_oco")
            if ev is None:
                return []
            if ev_mode == "mean":
                p_lcb = getattr(ev, "p_mean")()
                ev_lcb = p_lcb * sig["tp_pips"] - (1.0 - p_lcb) * sig["sl_pips"] - cost_pips
            else:
                ev_lcb = ev.ev_lcb_oco(sig["tp_pips"], sig["sl_pips"], cost_pips)
                p_lcb = ev.p_lcb()

            if ev_mode == "lcb" and (ev_lcb is None or ev_lcb < threshold):
                return []
        else:
            fallback = float(self.cfg.get("fallback_win_rate", 0.5) or 0.0)
            p_lcb = max(0.0, min(1.0, fallback))

        # Position sizing
        qty = compute_qty_from_ctx(
            ctx_data,
            sig["sl_pips"],
            mode="production",
            tp_pips=sig["tp_pips"],
            p_lcb=p_lcb,
        )

        if qty <= 0:
            self._last_gate_reason = {
                "stage": "sizing_guard",
                "qty": qty,
                "p_lcb": p_lcb,
                "sl_pips": sig["sl_pips"],
            }
            return []

        tag = f"day_orb5m#{sig['side']}"
        self.state["last_signal_bar"] = self.state["bar_idx"]
        self.state["broken"] = True  # block re-entry until next session reset
        self.state["signals_today"] = signals_today + 1
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
        session = ctx.get("session")
        if not allow_low and rv_band not in ("mid", "high"):
            self._last_gate_reason = {
                "stage": "rv_filter",
                "rv_band": rv_band,
            }
            return False

        if session == "NY" and rv_band == "high":
            # Optional hard block for scenarios where high RV moves during NY session
            # have proven too volatile for the OR breakout.
            ny_high_block = ctx.get("ny_high_rv_block")
            if ny_high_block is None:
                ny_high_block = self.cfg.get("ny_high_rv_block", False)
            if bool(ny_high_block):
                self._last_gate_reason = {
                    "stage": "ny_high_rv_block",
                    "session": session,
                    "rv_band": rv_band,
                }
                return False

            # Strengthen the OR/ATR requirement when NY volatility is elevated.
            override_min = ctx.get("ny_high_rv_min_or_atr_ratio")
            if override_min is None:
                override_min = self.cfg.get("ny_high_rv_min_or_atr_ratio")
            multiplier = ctx.get("ny_high_rv_or_multiplier")
            if multiplier is None:
                multiplier = self.cfg.get("ny_high_rv_or_multiplier", 1.0)

            ny_min: Optional[float] = None
            try:
                if override_min is not None:
                    ny_min = float(override_min)
            except (TypeError, ValueError):
                ny_min = None

            if ny_min is None and min_or:
                try:
                    mult = float(multiplier)
                except (TypeError, ValueError):
                    mult = 1.0
                if mult > 0:
                    ny_min = min_or * mult

            if ny_min and or_ratio < ny_min:
                reason = {
                    "stage": "ny_high_rv_or_filter",
                    "session": session,
                    "rv_band": rv_band,
                    "or_atr_ratio": or_ratio,
                    "ny_high_rv_min_or_atr_ratio": ny_min,
                }
                if min_or:
                    reason["min_or_atr_ratio"] = min_or
                try:
                    mult_val = float(multiplier)
                except (TypeError, ValueError):
                    mult_val = None
                if mult_val not in (None, 0.0, 1.0):
                    reason["ny_high_rv_or_multiplier"] = mult_val
                self._last_gate_reason = reason
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
