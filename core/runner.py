"""
Backtest/Replay Runner (skeleton)
- Validates 5m OHLC bars (minimal checks)
- Builds features and router context
- Runs DayORB5m strategy and simulates fills
- Updates EV estimators and collects simple metrics

NOTE: Placeholder thresholds and simplified assumptions to keep dependencies minimal.
"""
from __future__ import annotations
from typing import List, Dict, Any, Optional, Tuple
import json
import hashlib
from datetime import datetime, timezone
from dataclasses import dataclass, field

from strategies.day_orb_5m import DayORB5m
from core.feature_store import atr as calc_atr, adx as calc_adx, opening_range, realized_vol
from core.fill_engine import ConservativeFill, BridgeFill, OrderSpec
from core.ev_gate import BetaBinomialEV, TLowerEV
from core.pips import pip_size, price_to_pips
from router.router_v0 import pass_gates


def validate_bar(bar: Dict[str, Any]) -> bool:
    req = ["timestamp", "symbol", "tf", "o", "h", "l", "c", "v", "spread"]
    if not all(k in bar for k in req):
        return False
    if bar["tf"] != "5m":
        return False
    o, h, l, c = bar["o"], bar["h"], bar["l"], bar["c"]
    if not (l <= min(o, c) and h >= max(o, c) and l <= h):
        return False
    return True


@dataclass
class Metrics:
    trades: int = 0
    wins: int = 0
    total_pips: float = 0.0
    def as_dict(self):
        return {"trades": self.trades, "wins": self.wins, "total_pips": self.total_pips}


@dataclass
class RunnerConfig:
    threshold_lcb_pip: float = 0.5
    slip_cap_pip: float = 1.5
    min_or_atr_ratio: float = 0.6
    rv_band_cuts: List[float] = field(default_factory=lambda: [0.005, 0.015])  # tuned for 5m FX RV scale
    spread_bands: Dict[str, float] = field(default_factory=lambda: {"narrow": 0.5, "normal": 1.2, "wide": 99})
    allow_low_rv: bool = False
    # Strategy params
    or_n: int = 6
    k_tp: float = 1.0
    k_sl: float = 0.8
    k_tr: float = 0.0
    cooldown_bars: int = 3
    # EV warmup: number of signals to bypass EV gate (to bootstrap)
    warmup_trades: int = 0
    # EV prior (Beta-Binomial)
    prior_alpha: float = 0.0
    prior_beta: float = 0.0
    # Cost model: expected slippage option
    include_expected_slip: bool = False
    slip_curve: Dict[str, Dict[str, float]] = field(default_factory=lambda: {
        "narrow": {"a": 0.02, "b": 0.0},
        "normal": {"a": 0.05, "b": 0.0},
        "wide":   {"a": 0.10, "b": 0.0},
    })
    slip_learn: bool = True
    slip_ewma_alpha: float = 0.1
    # RV quantile calibration (session-wise)
    rv_qcalib_enabled: bool = False
    rv_q_low: float = 0.33
    rv_q_high: float = 0.66
    rv_q_lookback_bars: int = 5760  # ≈ 20d × 288 bars
    # Calibration phase (no-trade) to build EV counts without executing
    calibrate_days: int = 0
    # Simulation mode for EV/sizing: 'lcb' (default), 'off', 'mean'
    ev_mode: str = "lcb"
    # Minimal size multiplier when ev_mode='off'
    size_floor_mult: float = 0.01


class BacktestRunner:
    def __init__(self, equity: float, symbol: str, runner_cfg: Optional[RunnerConfig] = None, debug: bool = False, debug_sample_limit: int = 0):
        self.equity = equity
        self.symbol = symbol
        self.rcfg = runner_cfg or RunnerConfig()
        self.debug = debug
        self.debug_sample_limit = max(0, int(debug_sample_limit))
        self.ev_global = BetaBinomialEV(conf_level=0.95, decay=0.02,
                                        prior_alpha=self.rcfg.prior_alpha,
                                        prior_beta=self.rcfg.prior_beta)
        # bucket store for pooled EV
        self.ev_buckets: Dict[tuple, BetaBinomialEV] = {}
        self.ev_var = TLowerEV(conf_level=0.95, decay=0.02)
        self.fill_engine_c = ConservativeFill()
        self.fill_engine_b = BridgeFill()
        self.metrics = Metrics()
        self.window: List[Dict[str, Any]] = []
        self.session_bars: List[Dict[str, Any]] = []
        self.debug_counts: Dict[str,int] = {"no_breakout":0, "gate_block":0, "ev_reject":0, "zero_qty":0}
        self.debug_records: List[Dict[str,Any]] = []
        self.daily: Dict[str, Dict[str, Any]] = {}
        # RV quantile calibration state
        from collections import deque
        self.rv_hist: Dict[str, Any] = {
            "TOK": deque(maxlen=self.rcfg.rv_q_lookback_bars),
            "LDN": deque(maxlen=self.rcfg.rv_q_lookback_bars),
            "NY":  deque(maxlen=self.rcfg.rv_q_lookback_bars),
        }
        self.rv_thresh: Dict[str, Optional[tuple]] = {"TOK": None, "LDN": None, "NY": None}
        self.calib_positions: List[Dict[str, Any]] = []

        # strategy
        self.stg = DayORB5m()
        self.stg.on_start({"or_n": self.rcfg.or_n, "k_tp": self.rcfg.k_tp, "k_sl": self.rcfg.k_sl, "k_tr": self.rcfg.k_tr}, [symbol], {})
        self._warmup_left = max(0, int(self.rcfg.warmup_trades))

    # ---------- State persistence ----------
    def _config_fingerprint(self) -> str:
        cfg = {
            "symbol": self.symbol,
            "threshold_lcb_pip": self.rcfg.threshold_lcb_pip,
            "min_or_atr_ratio": self.rcfg.min_or_atr_ratio,
            "rv_band_cuts": self.rcfg.rv_band_cuts,
            "or_n": self.rcfg.or_n,
            "decay": self.ev_global.decay,
            "conf": self.ev_global.conf_level,
        }
        s = json.dumps(cfg, sort_keys=True)
        return hashlib.sha256(s.encode()).hexdigest()[:16]

    def export_state(self) -> Dict[str, Any]:
        buckets: Dict[str, Dict[str, float]] = {}
        for k, ev in self.ev_buckets.items():
            key = f"{k[0]}:{k[1]}:{k[2]}"
            buckets[key] = {"alpha": ev.alpha, "beta": ev.beta}
        state = {
            "meta": {
                "symbol": self.symbol,
                "config_fingerprint": self._config_fingerprint(),
            },
            "ev_global": {
                "alpha": self.ev_global.alpha,
                "beta": self.ev_global.beta,
                "prior_alpha": self.ev_global.prior_alpha,
                "prior_beta": self.ev_global.prior_beta,
                "decay": self.ev_global.decay,
                "conf": self.ev_global.conf_level,
            },
            "ev_buckets": buckets,
            "slip": {
                "a": getattr(self, "slip_a", None),
                "curve": self.rcfg.slip_curve,
                "ewma_alpha": getattr(self.rcfg, "slip_ewma_alpha", 0.1),
            },
            "rv_thresh": self.rv_thresh,
        }
        return state

    def load_state(self, state: Dict[str, Any]) -> None:
        try:
            meta = state.get("meta", {})
            # Optionally check fingerprint compatibility
            # fp = meta.get("config_fingerprint")
            evg = state.get("ev_global", {})
            self.ev_global.alpha = float(evg.get("alpha", self.ev_global.alpha))
            self.ev_global.beta = float(evg.get("beta", self.ev_global.beta))
            self.ev_global.prior_alpha = float(evg.get("prior_alpha", self.ev_global.prior_alpha))
            self.ev_global.prior_beta = float(evg.get("prior_beta", self.ev_global.prior_beta))
            # Buckets
            for key, v in state.get("ev_buckets", {}).items():
                try:
                    sess, spread, rv = key.split(":", 2)
                    k = (sess, spread, rv)
                    if k not in self.ev_buckets:
                        self.ev_buckets[k] = BetaBinomialEV(conf_level=self.ev_global.conf_level,
                                                            decay=self.ev_global.decay,
                                                            prior_alpha=self.ev_global.prior_alpha,
                                                            prior_beta=self.ev_global.prior_beta)
                    self.ev_buckets[k].alpha = float(v.get("alpha", 1.0))
                    self.ev_buckets[k].beta = float(v.get("beta", 1.0))
                except Exception:
                    continue
            # Slip
            slip = state.get("slip", {})
            a = slip.get("a")
            if a:
                self.slip_a = a
            # RV thresholds
            rv_th = state.get("rv_thresh")
            if rv_th:
                self.rv_thresh = rv_th
        except Exception:
            # Fallback: ignore loading errors to avoid crashing
            pass

    def load_state_file(self, path: str) -> None:
        try:
            with open(path, "r") as f:
                data = json.load(f)
            self.load_state(data)
        except Exception:
            pass

    def _band_spread(self, spread_pips: float) -> str:
        bands = self.rcfg.spread_bands
        if spread_pips <= bands["narrow"]:
            return "narrow"
        if spread_pips <= bands["normal"]:
            return "normal"
        return "wide"

    def _band_rv(self, rv: float, session: str) -> str:
        if self.rcfg.rv_qcalib_enabled and self.rv_thresh.get(session):
            c1, c2 = self.rv_thresh[session]
        else:
            c1, c2 = self.rcfg.rv_band_cuts
        if rv <= c1:
            return "low"
        if rv <= c2:
            return "mid"
        return "high"

    def _ev_key(self, sess: str, spread_band: str, rv_band: str) -> tuple:
        return (sess, spread_band, rv_band)

    def _neighbor_keys(self, key: tuple) -> list:
        sess, spread, rv = key
        if rv == "mid":
            rv_neighbors = ["low","high"]
        elif rv == "low":
            rv_neighbors = ["mid"]
        else:
            rv_neighbors = ["mid"]
        return [(sess, spread, r) for r in rv_neighbors]

    def _get_ev_manager(self, key: tuple):
        from core.ev_gate import PooledEVManager
        return PooledEVManager(self.ev_buckets, self.ev_global, key, self._neighbor_keys(key))

    def _build_ctx(self, bar: Dict[str, Any], atr14: float, adx14: float, or_h: Optional[float], or_l: Optional[float]) -> Dict[str, Any]:
        ps = pip_size(self.symbol)
        spread_pips = bar["spread"] / ps  # assume spread is price units; convert to pips
        # OR quality
        or_ratio = 0.0
        if or_h is not None and or_l is not None and atr14 and atr14 > 0:
            or_ratio = (or_h - or_l) / (atr14)

        sess = self._session_of_ts(bar.get("timestamp", ""))
        ctx = {
            "session": sess,
            "spread_band": self._band_spread(spread_pips),
            "rv_band": self._band_rv(realized_vol(self.window, n=12) or 0.0, sess),
            "expected_slip_pip": 0.2,
            "slip_cap_pip": self.rcfg.slip_cap_pip,
            "threshold_lcb_pip": self.rcfg.threshold_lcb_pip,
            "or_atr_ratio": or_ratio,
            "min_or_atr_ratio": self.rcfg.min_or_atr_ratio,
            "allow_low_rv": self.rcfg.allow_low_rv,
            "warmup_left": self._warmup_left,
            "warmup_mult": 0.05,
            "cooldown_bars": self.rcfg.cooldown_bars,
            "ev_mode": self.rcfg.ev_mode,
            "size_floor_mult": self.rcfg.size_floor_mult,
            # EV & sizing
            # pooled EV manager per bucket
            # ev_oco object provides p_lcb/ev_lcb_oco/update
            "ev_oco": None,
            "cost_pips": spread_pips,  # Treat 'spread' column as round-trip cost in pips
            "equity": self.equity,
            "pip_value": 10.0,  # placeholder; typically derived from notional
            "sizing_cfg": {"risk_per_trade_pct": 0.25, "kelly_fraction": 0.25, "units_cap": 5.0, "max_trade_loss_pct": 0.5},
        }
        key = self._ev_key(ctx["session"], ctx["spread_band"], ctx["rv_band"])
        ctx["ev_key"] = key
        ctx["ev_oco"] = self._get_ev_manager(key)
        return ctx

    def _session_of_ts(self, ts: str) -> str:
        """Very simple UTC-based session mapping.
        - TOK: 00:00–07:59 (inclusive of first hour), outside LDN/NY
        - LDN: 08:00–12:59
        - NY : 13:00–21:59
        else: TOK
        """
        try:
            hh = int(ts[11:13])
        except Exception:
            return "TOK"
        if 8 <= hh <= 12:
            return "LDN"
        if 13 <= hh <= 21:
            return "NY"
        return "TOK"

    def run(self, bars: List[Dict[str, Any]], mode: str = "conservative") -> Metrics:
        ps = pip_size(self.symbol)
        last_session: Optional[str] = None
        last_day: Optional[int] = None
        current_date: Optional[str] = None
        day_count: int = 0
        for bar in bars:
            if not validate_bar(bar):
                continue
            # Detect UTC day change for daily OR reset
            try:
                ts = bar.get("timestamp")
                # Accept both 'Z' and naive; fallback simple parse
                if isinstance(ts, str):
                    # Fast parse yyyy-mm-ddThh:mm:ss[Z]
                    day = int(ts[8:10])
                    date_str = ts[:10]
                    sess = self._session_of_ts(ts)
                else:
                    day = None
                    date_str = None
                    sess = "TOK"
            except Exception:
                day = None
                date_str = None
                sess = "TOK"
            new_session = False
            # session boundary reset: on first bar or when session changes
            if last_session is None or sess != last_session:
                new_session = True
            last_session = sess
            if day is not None:
                if last_day is None:
                    last_day = day
                elif day != last_day:
                    last_day = day
            if date_str and date_str != current_date:
                current_date = date_str
                day_count += 1
                if current_date not in self.daily:
                    self.daily[current_date] = {"breakouts":0, "gate_pass":0, "gate_block":0, "ev_pass":0, "ev_reject":0, "fills":0, "wins":0, "pnl_pips":0.0}
                # Recompute RV thresholds daily based on history (no future leak)
                if self.rcfg.rv_qcalib_enabled:
                    for s in ("TOK","LDN","NY"):
                        hist = list(self.rv_hist[s])
                        if len(hist) >= max(100, int(self.rcfg.rv_q_lookback_bars*0.2)):
                            hist_sorted = sorted(hist)
                            def quantile(arr, q):
                                if not arr: return None
                                k = max(0, min(len(arr)-1, int(q*(len(arr)-1))))
                                return arr[k]
                            c1 = quantile(hist_sorted, self.rcfg.rv_q_low)
                            c2 = quantile(hist_sorted, self.rcfg.rv_q_high)
                            if c1 is not None and c2 is not None and c1 <= c2:
                                self.rv_thresh[s] = (c1, c2)
            # maintain rolling window and compute features
            self.window.append({k: bar[k] for k in ("o","h","l","c")})
            if len(self.window) > 200:
                self.window.pop(0)
            # maintain session bars from session start
            if new_session:
                self.session_bars = []
            self.session_bars.append({k: bar[k] for k in ("o","h","l","c")})
            # append RV to session-wise history for quantile calibration
            try:
                sess_key = sess
            except NameError:
                sess_key = self._session_of_ts(bar.get("timestamp", ""))
            try:
                rv_val = realized_vol(self.window, n=12) or 0.0
                self.rv_hist[sess_key].append(rv_val)
            except Exception:
                pass
            atr14 = calc_atr(self.window[-15:]) if len(self.window) >= 15 else float("nan")
            adx14 = calc_adx(self.window[-15:]) if len(self.window) >= 15 else float("nan")
            or_h, or_l = opening_range(self.session_bars, n=self.rcfg.or_n)

            bar_input = {
                "o": bar["o"], "h": bar["h"], "l": bar["l"], "c": bar["c"],
                "atr14": atr14 if atr14 == atr14 else 0.0,  # nan->0.0
                "window": self.session_bars[: self.rcfg.or_n],
                "new_session": new_session,
            }
            ctx = self._build_ctx(bar, bar_input["atr14"], adx14, or_h if or_h==or_h else None, or_l if or_l==or_l else None)
            # inject ctx for strategy
            # calibration flag: bypass EV threshold inside strategy by lowering threshold
            calibrating = (self.rcfg.calibrate_days > 0 and day_count <= self.rcfg.calibrate_days)
            if calibrating:
                ctx["threshold_lcb_pip"] = -1e9
                ctx["calibrating"] = True
            self.stg.cfg["ctx"] = ctx

            # If a position is open, manage exits first (carry-over OCO)
            if getattr(self, "pos", None) is not None:
                side = self.pos["side"]
                entry_px = self.pos["entry_px"]
                tp_px = self.pos["tp_px"]
                sl_px = self.pos["sl_px"]
                # Trailing update
                if self.pos.get("trail_pips", 0.0) > 0:
                    if side == "BUY":
                        self.pos["hh"] = max(self.pos.get("hh", entry_px), bar["h"])
                        new_sl = self.pos["hh"] - self.pos["trail_pips"] * ps
                        sl_px = max(sl_px, new_sl)
                    else:
                        self.pos["ll"] = min(self.pos.get("ll", entry_px), bar["l"])
                        new_sl = self.pos["ll"] + self.pos["trail_pips"] * ps
                        sl_px = min(sl_px, new_sl)
                    self.pos["sl_px"] = sl_px

                exited = False
                exit_px = None
                exit_reason = None
                if side == "BUY":
                    if bar["l"] <= sl_px and bar["h"] >= tp_px:
                        if mode == "conservative":
                            exit_px, exit_reason = sl_px, "sl"
                        else:
                            rng = max(bar["h"] - bar["l"], ps)
                            drift = (bar["c"] - bar["o"]) / rng if rng>0 else 0.0
                            import math
                            d_tp = max((tp_px - entry_px)/ps, 1e-9)
                            d_sl = max((entry_px - sl_px)/ps, 1e-9)
                            base = d_sl/(d_tp+d_sl)
                            p_tp = min(0.999, max(0.001, 0.65*base + 0.35*0.5*(1.0+math.tanh(2.5*drift))))
                            exit_px = p_tp*tp_px + (1-p_tp)*sl_px
                            exit_reason = "tp" if p_tp>=0.5 else "sl"
                        exited = True
                    elif bar["l"] <= sl_px:
                        exit_px, exit_reason, exited = sl_px, "sl", True
                    elif bar["h"] >= tp_px:
                        exit_px, exit_reason, exited = tp_px, "tp", True
                else:
                    if bar["h"] >= sl_px and bar["l"] <= tp_px:
                        if mode == "conservative":
                            exit_px, exit_reason = sl_px, "sl"
                        else:
                            rng = max(bar["h"] - bar["l"], ps)
                            drift = (bar["o"] - bar["c"]) / rng if rng>0 else 0.0
                            import math
                            d_tp = max((entry_px - tp_px)/ps, 1e-9)
                            d_sl = max((sl_px - entry_px)/ps, 1e-9)
                            base = d_sl/(d_tp+d_sl)
                            p_tp = min(0.999, max(0.001, 0.65*base + 0.35*0.5*(1.0+math.tanh(2.5*drift))))
                            exit_px = p_tp*tp_px + (1-p_tp)*sl_px
                            exit_reason = "tp" if p_tp>=0.5 else "sl"
                        exited = True
                    elif bar["h"] >= sl_px:
                        exit_px, exit_reason, exited = sl_px, "sl", True
                    elif bar["l"] <= tp_px:
                        exit_px, exit_reason, exited = tp_px, "tp", True

                if not exited:
                    self.pos["hold"] = self.pos.get("hold", 0) + 1
                    if new_session or self.pos["hold"] >= getattr(self.rcfg, "max_hold_bars", 96):
                        exit_px, exit_reason, exited = bar["o"], ("session_end" if new_session else "timeout"), True

                if exited:
                    signed = +1 if side == "BUY" else -1
                    pnl_px = (exit_px - entry_px) * signed
                    cost = ctx.get("cost_pips", 0.0)
                    if self.rcfg.include_expected_slip:
                        band = ctx.get("spread_band", "normal")
                        curve = self.rcfg.slip_curve.get(band, {"a":0.0,"b":0.0})
                        qty = self.pos.get("qty", 1.0)
                        cost += float(curve.get("a",0.0))*qty + float(curve.get("b",0.0))
                    pnl_pips = price_to_pips(pnl_px, self.symbol) - cost
                    self.metrics.trades += 1
                    self.metrics.total_pips += pnl_pips
                    if exit_reason == "tp":
                        self.metrics.wins += 1
                    # update EV models
                    ev_key = self.pos.get("ev_key", (ctx["session"], ctx["spread_band"], ctx["rv_band"]))
                    self._get_ev_manager(ev_key).update(exit_reason == "tp")
                    self.ev_var.update(pnl_pips)
                    if current_date:
                        self.daily[current_date]["fills"] += 1
                        if exit_reason == "tp":
                            self.daily[current_date]["wins"] += 1
                        self.daily[current_date]["pnl_pips"] += pnl_pips
                    self.pos = None
                # Skip new entries while a position is open (or just exited this bar)
                continue

            # During calibration phase, resolve calibration positions (no metrics, only EV updates)
            calibrating = (self.rcfg.calibrate_days > 0 and day_count <= self.rcfg.calibrate_days)
            if calibrating and self.calib_positions:
                still: List[Dict[str, Any]] = []
                for p in self.calib_positions:
                    side = p["side"]; entry_px = p["entry_px"]; tp_px = p["tp_px"]; sl_px = p["sl_px"]
                    exited = False; exit_reason = None
                    if side == "BUY":
                        if bar["l"] <= sl_px and bar["h"] >= tp_px: exit_reason, exited = "sl", True
                        elif bar["l"] <= sl_px: exit_reason, exited = "sl", True
                        elif bar["h"] >= tp_px: exit_reason, exited = "tp", True
                    else:
                        if bar["h"] >= sl_px and bar["l"] <= tp_px: exit_reason, exited = "sl", True
                        elif bar["h"] >= sl_px: exit_reason, exited = "sl", True
                        elif bar["l"] <= tp_px: exit_reason, exited = "tp", True
                    p["hold"] = p.get("hold", 0) + 1
                    if not exited and (new_session or p["hold"] >= getattr(self.rcfg, "max_hold_bars", 96)):
                        exit_reason, exited = "timeout", True
                    if exited:
                        hit = (exit_reason == "tp")
                        self._get_ev_manager(p.get("ev_key", (ctx["session"], ctx["spread_band"], ctx["rv_band"])) ).update(bool(hit))
                    else:
                        still.append(p)
                self.calib_positions = still

            # strategy step
            self.stg.on_bar(bar_input)
            # Inspect pending signal for diagnostics
            pending = getattr(self.stg, "_pending_signal", None)
            if pending is None:
                self.debug_counts["no_breakout"] += 1
                if self.debug and self.debug_sample_limit and len(self.debug_records) < self.debug_sample_limit:
                    self.debug_records.append({"ts": bar.get("timestamp"), "stage": "no_breakout"})
                continue
            if current_date:
                self.daily[current_date]["breakouts"] += 1

            # Recompute gating/EV/sizing locally for transparent diagnostics
            ctx_dbg = self._build_ctx(bar, bar_input["atr14"], adx14, or_h if or_h==or_h else None, or_l if or_l==or_l else None)
            if not pass_gates(ctx_dbg):
                self.debug_counts["gate_block"] += 1
                if current_date:
                    self.daily[current_date]["gate_block"] += 1
                if self.debug and self.debug_sample_limit and len(self.debug_records) < self.debug_sample_limit:
                    self.debug_records.append({
                        "ts": bar.get("timestamp"), "stage": "gate_block",
                        "side": pending.get("side"),
                        "rv_band": ctx_dbg.get("rv_band"), "spread_band": ctx_dbg.get("spread_band"),
                        "or_atr_ratio": ctx_dbg.get("or_atr_ratio")
                    })
                continue
            if current_date:
                self.daily[current_date]["gate_pass"] += 1

            ev_mgr_dbg = self._get_ev_manager(ctx_dbg.get("ev_key", (ctx_dbg["session"], ctx_dbg["spread_band"], ctx_dbg["rv_band"])))
            calibrating = (self.rcfg.calibrate_days > 0 and day_count <= self.rcfg.calibrate_days)
            ev_lcb = ev_mgr_dbg.ev_lcb_oco(pending["tp_pips"], pending["sl_pips"], ctx_dbg["cost_pips"]) if (pending and not calibrating) else 1e9
            ev_bypass = False
            if not calibrating and ev_lcb < self.rcfg.threshold_lcb_pip:
                if self._warmup_left > 0:
                    # Bypass EV during warmup to bootstrap stats; do not size-debug
                    ev_bypass = True
                    self.debug_counts["ev_bypass"] = self.debug_counts.get("ev_bypass", 0) + 1
                else:
                    self.debug_counts["ev_reject"] += 1
                    if current_date:
                        self.daily[current_date]["ev_reject"] += 1
                    if self.debug and self.debug_sample_limit and len(self.debug_records) < self.debug_sample_limit:
                        self.debug_records.append({
                            "ts": bar.get("timestamp"), "stage": "ev_reject",
                            "side": pending.get("side"),
                            "ev_lcb": ev_lcb, "cost_pips": ctx_dbg.get("cost_pips"),
                            "tp_pips": pending.get("tp_pips"), "sl_pips": pending.get("sl_pips")
                        })
                    continue
            else:
                if current_date:
                    self.daily[current_date]["ev_pass"] += 1

            # Sizing (skip debug size check during EV bypass; strategy will warmup-size)
            if not ev_bypass and not calibrating:
                # Mirror the strategy calcs but minimal to avoid import cycle
                p_lcb = ev_mgr_dbg.p_lcb()
                b = pending["tp_pips"] / max(pending["sl_pips"], 1e-9)
                f_star = max(0.0, p_lcb - (1.0 - p_lcb)/b)
                kelly_fraction = 0.25
                mult = min(5.0, kelly_fraction * f_star)
                risk_amt = self.equity * (0.25/100.0)
                base = max(0.0, risk_amt / max(10.0*pending["sl_pips"], 1e-9))  # assumes pip_value=10
                qty_dbg = max(0.0, min(base * mult, (self.equity*(0.5/100.0))/(10.0*pending["sl_pips"]), 5.0))
                if qty_dbg <= 0:
                    self.debug_counts["zero_qty"] += 1
                    continue

            # If we get here, intents should exist; call signals() for real order emission
            intents = list(self.stg.signals())
            if not intents:
                # Safety: count as generic block
                self.debug_counts["gate_block"] += 1
                continue
            if self._warmup_left > 0:
                self._warmup_left -= 1

            # simulate fills (first intent only for skeleton)
            it = intents[0]
            spec = OrderSpec(side=it.side, entry=it.price, tp_pips=it.oco["tp_pips"], sl_pips=it.oco["sl_pips"], trail_pips=it.oco.get("trail_pips",0.0), slip_cap_pip=ctx["slip_cap_pip"])
            fe = self.fill_engine_c if mode == "conservative" else self.fill_engine_b
            result = fe.simulate({"o": bar["o"], "h": bar["h"], "l": bar["l"], "c": bar["c"], "pip": ps, "spread": bar["spread"]}, spec)
            if not result.get("fill"):
                continue

            # If immediate TP/SL inside bar, record; else carry over
            if "exit_px" in result:
                entry_px, exit_px = result["entry_px"], result["exit_px"]
                if calibrating:
                    # Only update EV counts; no metrics, no positions
                    # If Bridge (both reachable) returned mixture, approximate via hit bool or skip
                    hit = result.get("exit_reason") == "tp"
                    ev_mgr_dbg.update(bool(hit))
                    continue
                # Learn slippage a (per band) if enabled
                if self.rcfg.include_expected_slip and getattr(self, 'slip_learn', None) is None:
                    pass
                if self.rcfg.include_expected_slip and getattr(self.rcfg, 'slip_learn', True):
                    band = ctx.get("spread_band", "normal")
                    qty = getattr(it, 'qty', 1.0) or 1.0
                    slip_pips = abs(price_to_pips(entry_px - it.price, self.symbol))
                    sample_a = slip_pips / max(qty, 1e-9)
                    if not hasattr(self, 'slip_a'):
                        self.slip_a = {"narrow": self.rcfg.slip_curve["narrow"]["a"],
                                       "normal": self.rcfg.slip_curve["normal"]["a"],
                                       "wide":   self.rcfg.slip_curve["wide"]["a"]}
                    alpha = getattr(self.rcfg, 'slip_ewma_alpha', 0.1)
                    self.slip_a[band] = (1-alpha)*self.slip_a.get(band, sample_a) + alpha*sample_a
                signed = +1 if it.side == "BUY" else -1
                pnl_px = (exit_px - entry_px) * signed
                # Cost: spread + optional expected slippage (band×qty)
                cost = ctx.get("cost_pips", 0.0)
                if self.rcfg.include_expected_slip:
                    band = ctx.get("spread_band", "normal")
                    # choose learned 'a' if learning is enabled
                    if getattr(self.rcfg, 'slip_learn', True) and hasattr(self, 'slip_a'):
                        a = float(self.slip_a.get(band, self.rcfg.slip_curve.get(band, {"a":0.0}).get("a", 0.0)))
                        b = float(self.rcfg.slip_curve.get(band, {"b":0.0}).get("b", 0.0))
                        curve = {"a": a, "b": b}
                    else:
                        curve = self.rcfg.slip_curve.get(band, {"a":0.0,"b":0.0})
                    qty = getattr(it, 'qty', 1.0) or 1.0
                    cost += float(curve.get("a",0.0))*qty + float(curve.get("b",0.0))
                pnl_pips = price_to_pips(pnl_px, self.symbol) - cost
                self.metrics.trades += 1
                self.metrics.total_pips += pnl_pips
                hit = result.get("exit_reason") == "tp"
                if hit:
                    self.metrics.wins += 1
                if current_date:
                    self.daily[current_date]["fills"] += 1
                    if hit:
                        self.daily[current_date]["wins"] += 1
                    self.daily[current_date]["pnl_pips"] += pnl_pips
                if self.debug and self.debug_sample_limit and len(self.debug_records) < self.debug_sample_limit:
                    self.debug_records.append({
                        "ts": bar.get("timestamp"), "stage": "trade", "side": it.side,
                        "tp_pips": spec.tp_pips, "sl_pips": spec.sl_pips, "cost_pips": ctx.get("cost_pips"),
                        "exit": result.get("exit_reason"), "pnl_pips": pnl_pips
                    })
                # Update pooled EV for the bucket
                self._get_ev_manager(ctx.get("ev_key", (ctx["session"], ctx["spread_band"], ctx["rv_band"])) ).update(bool(hit))
                self.ev_var.update(pnl_pips)
            else:
                # Open position to next bars
                if calibrating:
                    entry_px = result.get("entry_px")
                    tp_px = it.price + (spec.tp_pips * ps if it.side == "BUY" else -spec.tp_pips * ps)
                    sl_px0 = it.price - (spec.sl_pips * ps if it.side == "BUY" else -spec.sl_pips * ps)
                    self.calib_positions.append({
                        "side": it.side,
                        "entry_px": entry_px,
                        "tp_px": tp_px,
                        "sl_px": sl_px0,
                        "ev_key": ctx.get("ev_key", (ctx["session"], ctx["spread_band"], ctx["rv_band"])) ,
                        "hold": 0,
                    })
                    continue
                entry_px = result.get("entry_px")
                tp_px = it.price + (spec.tp_pips * ps if it.side == "BUY" else -spec.tp_pips * ps)
                sl_px0 = it.price - (spec.sl_pips * ps if it.side == "BUY" else -spec.sl_pips * ps)
                self.pos = {
                    "side": it.side,
                    "entry_px": entry_px,
                    "tp_px": tp_px,
                    "sl_px": sl_px0,
                    "trail_pips": spec.trail_pips,
                    "hh": bar["h"],
                    "ll": bar["l"],
                    "ev_key": ctx.get("ev_key", (ctx["session"], ctx["spread_band"], ctx["rv_band"])) ,
                    "qty": getattr(it, 'qty', 1.0) or 1.0,
                    "hold": 0,
                }

        # If debug, attach counts for external inspection
        if self.debug:
            self.metrics.debug = getattr(self.metrics, 'debug', {})
            self.metrics.debug.update(self.debug_counts)
            if self.debug_sample_limit:
                self.metrics.records = getattr(self.metrics, 'records', [])
                self.metrics.records.extend(self.debug_records)
            if self.daily:
                self.metrics.daily = self.daily
        return self.metrics
