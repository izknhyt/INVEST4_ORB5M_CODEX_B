"""
Backtest/Replay Runner (skeleton)
- Validates 5m OHLC bars (minimal checks)
- Builds features and router context
- Runs DayORB5m strategy and simulates fills
- Updates EV estimators and collects simple metrics

NOTE: Placeholder thresholds and simplified assumptions to keep dependencies minimal.
"""
from __future__ import annotations
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple
from collections import deque
import json
import hashlib
import math
from datetime import datetime, timezone
from dataclasses import dataclass, field

from strategies.day_orb_5m import DayORB5m
from core.strategy_api import Strategy
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
    trade_returns: List[float] = field(default_factory=list)
    equity_curve: List[float] = field(default_factory=list)
    records: List[Dict[str, Any]] = field(default_factory=list)
    daily: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    debug: Dict[str, Any] = field(default_factory=dict)
    starting_equity: float = 0.0

    def __post_init__(self) -> None:
        if not self.equity_curve:
            self.equity_curve.append(float(self.starting_equity))

    def record_trade(self, pnl_pips: float, hit: bool) -> None:
        pnl_val = float(pnl_pips)
        self.trades += 1
        self.total_pips += pnl_val
        if hit:
            self.wins += 1
        self.trade_returns.append(pnl_val)
        if not self.equity_curve:
            self.equity_curve.append(float(self.starting_equity))
        last_equity = self.equity_curve[-1]
        self.equity_curve.append(last_equity + pnl_val)

    def as_dict(self):
        win_rate: Optional[float]
        if self.trades:
            win_rate = self.wins / float(self.trades)
        else:
            win_rate = None

        return {
            "trades": self.trades,
            "wins": self.wins,
            "win_rate": win_rate,
            "total_pips": self.total_pips,
            "sharpe": self._compute_sharpe(),
            "max_drawdown": self._compute_max_drawdown(),
        }

    def _compute_sharpe(self) -> Optional[float]:
        if not self.trade_returns:
            return None
        n = len(self.trade_returns)
        if n < 2:
            return 0.0
        mean_ret = sum(self.trade_returns) / n
        variance = sum((r - mean_ret) ** 2 for r in self.trade_returns) / n
        std_dev = math.sqrt(variance)
        if std_dev == 0.0:
            return 0.0
        return mean_ret / std_dev * math.sqrt(float(n))

    def _compute_max_drawdown(self) -> Optional[float]:
        if not self.equity_curve:
            return None
        peak = self.equity_curve[0]
        max_drawdown = 0.0
        for equity in self.equity_curve:
            if equity > peak:
                peak = equity
            drawdown = equity - peak
            if drawdown < max_drawdown:
                max_drawdown = drawdown
        return max_drawdown


@dataclass
class StrategyConfig:
    """Container for strategy-specific parameters.

    The default attributes mirror the Day ORB setup but the structure now
    supports arbitrary key/value pairs so manifests can pass through new
    knobs without requiring core changes.
    """

    or_n: int = 6
    k_tp: float = 1.0
    k_sl: float = 0.8
    k_tr: float = 0.0
    cooldown_bars: int = 3
    extra_params: Dict[str, Any] = field(default_factory=dict)

    def merge(self, params: Dict[str, Any], *, replace: bool = False) -> None:
        """Merge arbitrary parameters into the config.

        Parameters that match the built-in attributes are coerced into the
        appropriate type; everything else is stored in ``extra_params`` so it
        can be forwarded verbatim to ``Strategy.on_start``.
        """

        if replace:
            self.extra_params = {}
        if not params:
            return
        for key, value in params.items():
            if key == "or_n" and value is not None:
                self.or_n = int(value)
            elif key == "k_tp" and value is not None:
                self.k_tp = float(value)
            elif key == "k_sl" and value is not None:
                self.k_sl = float(value)
            elif key == "k_tr" and value is not None:
                self.k_tr = float(value)
            elif key == "cooldown_bars" and value is not None:
                self.cooldown_bars = int(value)
            else:
                self.extra_params[key] = value

    def as_dict(self) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "or_n": self.or_n,
            "k_tp": self.k_tp,
            "k_sl": self.k_sl,
            "k_tr": self.k_tr,
            "cooldown_bars": self.cooldown_bars,
        }
        params.update(self.extra_params)
        return params


@dataclass
class RunnerConfig:
    threshold_lcb_pip: float = 0.5
    slip_cap_pip: float = 1.5
    min_or_atr_ratio: float = 0.6
    rv_band_cuts: List[float] = field(default_factory=lambda: [0.005, 0.015])  # tuned for 5m FX RV scale
    spread_bands: Dict[str, float] = field(default_factory=lambda: {"narrow": 0.5, "normal": 1.2, "wide": 99})
    allow_low_rv: bool = False
    allowed_sessions: Tuple[str, ...] = ("LDN", "NY")
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    # EV warmup: number of signals to bypass EV gate (to bootstrap)
    warmup_trades: int = 50
    # EV prior (Beta-Binomial)
    prior_alpha: float = 0.0
    prior_beta: float = 0.0
    # EV decay (EWMA smoothing for win-rate updates)
    ev_decay: float = 0.02
    # Risk controls sourced from manifests
    risk_per_trade_pct: float = 0.0
    max_daily_dd_pct: Optional[float] = None
    notional_cap: Optional[float] = None
    max_concurrent_positions: int = 1
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

    @property
    def or_n(self) -> int:
        return self.strategy.or_n

    @or_n.setter
    def or_n(self, value: int) -> None:
        self.strategy.or_n = int(value)

    @property
    def k_tp(self) -> float:
        return self.strategy.k_tp

    @k_tp.setter
    def k_tp(self, value: float) -> None:
        self.strategy.k_tp = float(value)

    @property
    def k_sl(self) -> float:
        return self.strategy.k_sl

    @k_sl.setter
    def k_sl(self, value: float) -> None:
        self.strategy.k_sl = float(value)

    @property
    def k_tr(self) -> float:
        return self.strategy.k_tr

    @k_tr.setter
    def k_tr(self, value: float) -> None:
        self.strategy.k_tr = float(value)

    @property
    def cooldown_bars(self) -> int:
        return self.strategy.cooldown_bars

    @cooldown_bars.setter
    def cooldown_bars(self, value: int) -> None:
        self.strategy.cooldown_bars = int(value)

    def merge_strategy_params(self, params: Dict[str, Any], *, replace: bool = False) -> None:
        self.strategy.merge(params, replace=replace)


class BacktestRunner:
    DEBUG_COUNT_KEYS: Tuple[str, ...] = (
        "no_breakout",
        "gate_block",
        "ev_reject",
        "ev_bypass",
        "zero_qty",
        "strategy_gate_error",
        "ev_threshold_error",
    )
    DEBUG_RECORD_FIELDS: Dict[str, Tuple[str, ...]] = {
        "no_breakout": ("ts",),
        "strategy_gate": ("ts", "side", "reason_stage", "or_atr_ratio", "min_or_atr_ratio", "rv_band", "allow_low_rv"),
        "strategy_gate_error": ("ts", "side", "error"),
        "gate_block": ("ts", "side", "rv_band", "spread_band", "or_atr_ratio", "reason"),
        "slip_cap": ("ts", "side", "expected_slip_pip", "slip_cap_pip"),
        "ev_reject": ("ts", "side", "ev_lcb", "threshold_lcb", "cost_pips", "tp_pips", "sl_pips"),
        "ev_threshold_error": ("ts", "side", "base_threshold", "error"),
        "trade": ("ts", "side", "tp_pips", "sl_pips", "cost_pips", "slip_est", "slip_real", "exit", "pnl_pips"),
        "trade_exit": ("ts", "side", "cost_pips", "slip_est", "slip_real", "exit", "pnl_pips"),
    }

    def __init__(self, equity: float, symbol: str, runner_cfg: Optional[RunnerConfig] = None,
                 debug: bool = False, debug_sample_limit: int = 0,
                 strategy_cls: Optional[type[Strategy]] = None,
                 ev_profile: Optional[Dict[str, Any]] = None):
        self.equity = equity
        self.symbol = symbol
        self.rcfg = runner_cfg or RunnerConfig()
        self.debug = debug
        self.debug_sample_limit = max(0, int(debug_sample_limit))
        self.strategy_cls = strategy_cls or DayORB5m
        self.ev_profile = ev_profile or {}
        self.ev_global = BetaBinomialEV(conf_level=0.95, decay=self.rcfg.ev_decay,
                                        prior_alpha=self.rcfg.prior_alpha,
                                        prior_beta=self.rcfg.prior_beta)
        # bucket store for pooled EV
        self.ev_buckets: Dict[tuple, BetaBinomialEV] = {}
        self.ev_var = TLowerEV(conf_level=0.95, decay=self.rcfg.ev_decay)
        self.fill_engine_c = ConservativeFill()
        self.fill_engine_b = BridgeFill()
        self._reset_runtime_state()
        self._ev_profile_lookup: Dict[tuple, Dict[str, Any]] = {}
        # Slip/size expectation tracking
        self.slip_a = {
            "narrow": self.rcfg.slip_curve.get("narrow", {}).get("a", 0.0),
            "normal": self.rcfg.slip_curve.get("normal", {}).get("a", 0.0),
            "wide":   self.rcfg.slip_curve.get("wide", {}).get("a", 0.0),
        }
        self.qty_ewma: Dict[str, float] = {"narrow": 0.0, "normal": 0.0, "wide": 0.0}

        # strategy
        self.stg = self.strategy_cls()
        self.stg.on_start(self.rcfg.strategy.as_dict(), [symbol], {})
        self._strategy_gate_hook = self._resolve_strategy_hook("strategy_gate")
        self._ev_threshold_hook = self._resolve_strategy_hook("ev_threshold")
        self._apply_ev_profile()

    def _reset_runtime_state(self) -> None:
        self.metrics = Metrics(starting_equity=self.equity)
        self.records: List[Dict[str, Any]] = []
        self.window: List[Dict[str, Any]] = []
        self.session_bars: List[Dict[str, Any]] = []
        self.debug_counts: Dict[str, int] = {key: 0 for key in self.DEBUG_COUNT_KEYS}
        self.debug_records: List[Dict[str, Any]] = []
        self.daily: Dict[str, Dict[str, Any]] = {}
        self.rv_hist: Dict[str, Any] = {
            "TOK": deque(maxlen=self.rcfg.rv_q_lookback_bars),
            "LDN": deque(maxlen=self.rcfg.rv_q_lookback_bars),
            "NY": deque(maxlen=self.rcfg.rv_q_lookback_bars),
        }
        self.rv_thresh: Dict[str, Optional[tuple]] = {"TOK": None, "LDN": None, "NY": None}
        self.calib_positions: List[Dict[str, Any]] = []
        self.pos: Optional[Dict[str, Any]] = None
        self._warmup_left = max(0, int(self.rcfg.warmup_trades))
        self._last_session: Optional[str] = None
        self._last_day: Optional[int] = None
        self._current_date: Optional[str] = None
        self._day_count: int = 0
        self._last_timestamp: Optional[str] = None

    def _resolve_strategy_hook(self, attr_name: str) -> Optional[Callable[..., Any]]:
        hook = getattr(self.stg, attr_name, None)
        if callable(hook):
            return hook
        return None

    def _append_debug_record(self, stage: str, **fields: Any) -> None:
        if not self.debug or not self.debug_sample_limit:
            return
        if len(self.debug_records) >= self.debug_sample_limit:
            return
        record: Dict[str, Any] = {"stage": stage}
        ts = fields.get("ts")
        if ts is not None:
            record["ts"] = ts
        allowed = self.DEBUG_RECORD_FIELDS.get(stage)
        if allowed:
            for key in allowed:
                if key == "ts":
                    continue
                value = fields.get(key)
                if value is not None:
                    record[key] = value
        else:
            for key, value in fields.items():
                if key == "ts" or value is None:
                    continue
                record[key] = value
        self.debug_records.append(record)

    def _call_strategy_gate(
        self,
        ctx_dbg: Dict[str, Any],
        pending: Dict[str, Any],
        *,
        ts: Optional[str],
        side: Optional[str],
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        if self._strategy_gate_hook is None:
            return True, None
        try:
            allowed = bool(self._strategy_gate_hook(ctx_dbg, pending))
        except Exception as exc:  # pragma: no cover - defensive diagnostics
            self.debug_counts["strategy_gate_error"] += 1
            self._append_debug_record(
                "strategy_gate_error",
                ts=ts,
                side=side,
                error=str(exc),
            )
            return True, None
        reason = getattr(self.stg, "_last_gate_reason", None)
        if isinstance(reason, dict):
            return allowed, reason
        return allowed, None

    def _call_ev_threshold(
        self,
        ctx_dbg: Dict[str, Any],
        pending: Dict[str, Any],
        base_threshold: float,
        *,
        ts: Optional[str],
        side: Optional[str],
    ) -> float:
        if self._ev_threshold_hook is None:
            return base_threshold
        try:
            threshold = float(self._ev_threshold_hook(ctx_dbg, pending, base_threshold))
        except Exception as exc:  # pragma: no cover - defensive diagnostics
            self.debug_counts["ev_threshold_error"] += 1
            self._append_debug_record(
                "ev_threshold_error",
                ts=ts,
                side=side,
                base_threshold=base_threshold,
                error=str(exc),
            )
            return base_threshold
        if not math.isfinite(threshold):
            self.debug_counts["ev_threshold_error"] += 1
            self._append_debug_record(
                "ev_threshold_error",
                ts=ts,
                side=side,
                base_threshold=base_threshold,
                error="non_finite",
            )
            return base_threshold
        return threshold

    def _update_slip_learning(
        self,
        *,
        order: Any,
        actual_price: float,
        intended_price: float,
        ctx: Mapping[str, Any],
    ) -> Tuple[float, float]:
        qty_value = getattr(order, "qty", 1.0) or 1.0
        qty_sample = float(qty_value)
        slip_actual = abs(price_to_pips(actual_price - intended_price, self.symbol))
        if getattr(self.rcfg, "include_expected_slip", False) and getattr(
            self.rcfg, "slip_learn", True
        ):
            band = ctx.get("spread_band", "normal")
            sample_a = slip_actual / max(qty_sample, 1e-9)
            alpha = getattr(self.rcfg, "slip_ewma_alpha", 0.1)
            self.slip_a[band] = (
                (1 - alpha) * self.slip_a.get(band, sample_a) + alpha * sample_a
            )
            self.qty_ewma[band] = (
                (1 - alpha) * self.qty_ewma.get(band, 0.0) + alpha * qty_sample
            )
        return qty_sample, slip_actual

    def _log_trade_record(
        self,
        *,
        exit_ts: Any,
        entry_ts: Any,
        side: str,
        tp_pips: float,
        sl_pips: float,
        cost_pips: float,
        slip_est: float,
        slip_real: float,
        exit_reason: Optional[str],
        pnl_pips: float,
        ctx_snapshot: Optional[Dict[str, Any]] = None,
    ) -> None:
        ctx_snapshot = ctx_snapshot or {}
        record = {
            "ts": exit_ts,
            "entry_ts": entry_ts,
            "stage": "trade",
            "side": side,
            "tp_pips": tp_pips,
            "sl_pips": sl_pips,
            "cost_pips": cost_pips,
            "slip_est": slip_est,
            "slip_real": slip_real,
            "exit": exit_reason,
            "pnl_pips": pnl_pips,
        }
        for key in (
            "session",
            "rv_band",
            "spread_band",
            "or_atr_ratio",
            "min_or_atr_ratio",
            "ev_lcb",
            "threshold_lcb",
            "ev_pass",
            "expected_slip_pip",
            "zscore",
        ):
            value = ctx_snapshot.get(key)
            if value is not None:
                record[key] = value
        if ctx_snapshot.get("cost_base") is not None:
            record["cost_base"] = ctx_snapshot["cost_base"]
        self.records.append(record)

    def _finalize_trade(
        self,
        *,
        exit_ts: Any,
        entry_ts: Any,
        side: str,
        entry_px: float,
        exit_px: float,
        exit_reason: Optional[str],
        ctx_snapshot: Mapping[str, Any],
        ctx: Mapping[str, Any],
        qty_sample: float,
        slip_actual: float,
        ev_key: Optional[tuple],
        tp_pips: float,
        sl_pips: float,
        debug_stage: str,
        debug_extra: Optional[Mapping[str, Any]] = None,
    ) -> None:
        base_cost = ctx_snapshot.get(
            "cost_base", ctx.get("base_cost_pips", ctx.get("cost_pips", 0.0))
        )
        est_slip_used = 0.0
        if getattr(self.rcfg, "include_expected_slip", False):
            band = ctx_snapshot.get(
                "spread_band", ctx.get("spread_band", "normal")
            )
            coeff = float(
                self.slip_a.get(
                    band, self.rcfg.slip_curve.get(band, {}).get("a", 0.0)
                )
            )
            intercept = float(
                self.rcfg.slip_curve.get(band, {}).get("b", 0.0)
            )
            est_slip_used = max(0.0, coeff * qty_sample + intercept)
        cost = base_cost + est_slip_used
        signed = 1 if side == "BUY" else -1
        pnl_px = (exit_px - entry_px) * signed
        pnl_pips = price_to_pips(pnl_px, self.symbol) - cost
        hit = exit_reason == "tp"
        self._record_trade_metrics(pnl_pips, hit)
        if self._current_date and self._current_date in self.daily:
            daily = self.daily[self._current_date]
            daily["fills"] += 1
            if hit:
                daily["wins"] += 1
            daily["pnl_pips"] += pnl_pips
            daily["slip_est"] += est_slip_used
            daily["slip_real"] += slip_actual
        self._log_trade_record(
            exit_ts=exit_ts,
            entry_ts=entry_ts,
            side=side,
            tp_pips=tp_pips,
            sl_pips=sl_pips,
            cost_pips=cost,
            slip_est=est_slip_used,
            slip_real=slip_actual,
            exit_reason=exit_reason,
            pnl_pips=pnl_pips,
            ctx_snapshot=dict(ctx_snapshot),
        )
        debug_fields: Dict[str, Any] = {
            "ts": self._last_timestamp,
            "side": side,
            "cost_pips": cost,
            "slip_est": est_slip_used,
            "slip_real": slip_actual,
            "exit": exit_reason,
            "pnl_pips": pnl_pips,
        }
        if debug_extra:
            debug_fields.update(debug_extra)
        self._append_debug_record(debug_stage, **debug_fields)
        session = ctx.get("session", "TOK")
        spread_band = ctx.get("spread_band", "normal")
        rv_band = ctx.get("rv_band")
        resolved_key = ev_key or ctx.get("ev_key") or (
            session,
            spread_band,
            rv_band,
        )
        self._get_ev_manager(resolved_key).update(hit)
        self.ev_var.update(pnl_pips)

    def _update_daily_state(
        self, bar: Dict[str, Any]
    ) -> Tuple[bool, str, bool]:
        try:
            ts = bar.get("timestamp")
        except Exception:
            ts = None
        day: Optional[int]
        date_str: Optional[str]
        sess = "TOK"
        try:
            if isinstance(ts, str):
                day = int(ts[8:10])
                date_str = ts[:10]
                sess = self._session_of_ts(ts)
                self._last_timestamp = ts
            else:
                day = None
                date_str = None
        except Exception:
            day = None
            date_str = None
        if not isinstance(ts, str) and isinstance(bar.get("timestamp"), str):
            self._last_timestamp = bar.get("timestamp")
        new_session = self._last_session is None or sess != self._last_session
        self._last_session = sess
        if day is not None:
            if self._last_day is None:
                self._last_day = day
            elif day != self._last_day:
                self._last_day = day
        if isinstance(date_str, str) and date_str != self._current_date:
            self._current_date = date_str
            self._day_count += 1
            if self._current_date not in self.daily:
                self.daily[self._current_date] = {
                    "breakouts": 0,
                    "gate_pass": 0,
                    "gate_block": 0,
                    "ev_pass": 0,
                    "ev_reject": 0,
                    "fills": 0,
                    "wins": 0,
                    "pnl_pips": 0.0,
                    "slip_est": 0.0,
                    "slip_real": 0.0,
                }
            if self.rcfg.rv_qcalib_enabled:
                for session_name in ("TOK", "LDN", "NY"):
                    hist = list(self.rv_hist[session_name])
                    if len(hist) >= max(100, int(self.rcfg.rv_q_lookback_bars * 0.2)):
                        hist_sorted = sorted(hist)

                        def quantile(arr: List[float], q: float) -> Optional[float]:
                            if not arr:
                                return None
                            k = max(0, min(len(arr) - 1, int(q * (len(arr) - 1))))
                            return arr[k]

                        c1 = quantile(hist_sorted, self.rcfg.rv_q_low)
                        c2 = quantile(hist_sorted, self.rcfg.rv_q_high)
                        if c1 is not None and c2 is not None and c1 <= c2:
                            self.rv_thresh[session_name] = (c1, c2)
        calibrating = (
            self.rcfg.calibrate_days > 0
            and self._day_count <= self.rcfg.calibrate_days
        )
        return new_session, sess, calibrating

    def _compute_features(
        self,
        bar: Dict[str, Any],
        *,
        session: str,
        new_session: bool,
        calibrating: bool,
    ) -> Tuple[
        Dict[str, Any],
        Dict[str, Any],
        float,
        float,
        Optional[float],
        Optional[float],
    ]:
        self.window.append({k: bar[k] for k in ("o", "h", "l", "c")})
        if len(self.window) > 200:
            self.window.pop(0)
        if new_session:
            self.session_bars = []
        self.session_bars.append({k: bar[k] for k in ("o", "h", "l", "c")})
        try:
            rv_val = realized_vol(self.window, n=12) or 0.0
            self.rv_hist[session].append(rv_val)
        except Exception:
            pass
        atr14 = calc_atr(self.window[-15:]) if len(self.window) >= 15 else float("nan")
        adx14 = calc_adx(self.window[-15:]) if len(self.window) >= 15 else float("nan")
        or_h, or_l = opening_range(self.session_bars, n=self.rcfg.or_n)
        bar_input: Dict[str, Any] = {
            "o": bar["o"],
            "h": bar["h"],
            "l": bar["l"],
            "c": bar["c"],
            "atr14": atr14 if atr14 == atr14 else 0.0,
            "window": self.session_bars[: self.rcfg.or_n],
            "new_session": new_session,
        }
        if "zscore" in bar:
            zscore_val = bar["zscore"]
            try:
                zscore_val = float(zscore_val)
            except (TypeError, ValueError):
                pass
            bar_input["zscore"] = zscore_val
        ctx = self._build_ctx(
            bar,
            bar_input["atr14"],
            adx14,
            or_h if or_h == or_h else None,
            or_l if or_l == or_l else None,
        )
        if calibrating:
            ctx["threshold_lcb_pip"] = -1e9
            ctx["calibrating"] = True
        self.stg.cfg["ctx"] = ctx
        return bar_input, ctx, atr14, adx14, or_h, or_l

    def _handle_active_position(
        self,
        *,
        bar: Dict[str, Any],
        ctx: Mapping[str, Any],
        mode: str,
        pip_size_value: float,
        new_session: bool,
    ) -> bool:
        if getattr(self, "pos", None) is None:
            return False
        side = self.pos["side"]
        entry_px = self.pos["entry_px"]
        tp_px = self.pos["tp_px"]
        sl_px = self.pos["sl_px"]
        if self.pos.get("trail_pips", 0.0) > 0:
            if side == "BUY":
                self.pos["hh"] = max(self.pos.get("hh", entry_px), bar["h"])
                new_sl = self.pos["hh"] - self.pos["trail_pips"] * pip_size_value
                sl_px = max(sl_px, new_sl)
            else:
                self.pos["ll"] = min(self.pos.get("ll", entry_px), bar["l"])
                new_sl = self.pos["ll"] + self.pos["trail_pips"] * pip_size_value
                sl_px = min(sl_px, new_sl)
            self.pos["sl_px"] = sl_px
        exited = False
        exit_px = None
        exit_reason: Optional[str] = None
        if side == "BUY":
            if bar["l"] <= sl_px and bar["h"] >= tp_px:
                if mode == "conservative":
                    exit_px, exit_reason = sl_px, "sl"
                else:
                    rng = max(bar["h"] - bar["l"], pip_size_value)
                    drift = (bar["c"] - bar["o"]) / rng if rng > 0 else 0.0
                    d_tp = max((tp_px - entry_px) / pip_size_value, 1e-9)
                    d_sl = max((entry_px - sl_px) / pip_size_value, 1e-9)
                    base = d_sl / (d_tp + d_sl)
                    p_tp = min(
                        0.999,
                        max(0.001, 0.65 * base + 0.35 * 0.5 * (1.0 + math.tanh(2.5 * drift))),
                    )
                    exit_px = p_tp * tp_px + (1 - p_tp) * sl_px
                    exit_reason = "tp" if p_tp >= 0.5 else "sl"
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
                    rng = max(bar["h"] - bar["l"], pip_size_value)
                    drift = (bar["o"] - bar["c"]) / rng if rng > 0 else 0.0
                    d_tp = max((entry_px - tp_px) / pip_size_value, 1e-9)
                    d_sl = max((sl_px - entry_px) / pip_size_value, 1e-9)
                    base = d_sl / (d_tp + d_sl)
                    p_tp = min(
                        0.999,
                        max(0.001, 0.65 * base + 0.35 * 0.5 * (1.0 + math.tanh(2.5 * drift))),
                    )
                    exit_px = p_tp * tp_px + (1 - p_tp) * sl_px
                    exit_reason = "tp" if p_tp >= 0.5 else "sl"
                exited = True
            elif bar["h"] >= sl_px:
                exit_px, exit_reason, exited = sl_px, "sl", True
            elif bar["l"] <= tp_px:
                exit_px, exit_reason, exited = tp_px, "tp", True
        if not exited:
            self.pos["hold"] = self.pos.get("hold", 0) + 1
            if new_session or self.pos["hold"] >= getattr(self.rcfg, "max_hold_bars", 96):
                exit_px = bar["o"]
                exit_reason = "session_end" if new_session else "timeout"
                exited = True
        if exited and exit_px is not None:
            qty_sample = self.pos.get("qty", 1.0) or 1.0
            slip_actual = self.pos.get("entry_slip_pip", 0.0)
            self._finalize_trade(
                exit_ts=bar.get("timestamp"),
                entry_ts=self.pos.get("entry_ts"),
                side=side,
                entry_px=entry_px,
                exit_px=exit_px,
                exit_reason=exit_reason,
                ctx_snapshot=self.pos.get("ctx_snapshot", {}),
                ctx=ctx,
                qty_sample=qty_sample,
                slip_actual=slip_actual,
                ev_key=self.pos.get("ev_key"),
                tp_pips=self.pos.get("tp_pips", 0.0),
                sl_pips=self.pos.get("sl_pips", 0.0),
                debug_stage="trade_exit",
            )
            self.pos = None
        return True

    def _resolve_calibration_positions(
        self,
        *,
        bar: Dict[str, Any],
        ctx: Mapping[str, Any],
        new_session: bool,
        calibrating: bool,
    ) -> None:
        if not calibrating or not self.calib_positions:
            return
        still: List[Dict[str, Any]] = []
        for pos in self.calib_positions:
            side = pos["side"]
            entry_px = pos["entry_px"]
            tp_px = pos["tp_px"]
            sl_px = pos["sl_px"]
            exited = False
            exit_reason: Optional[str] = None
            if side == "BUY":
                if bar["l"] <= sl_px and bar["h"] >= tp_px:
                    exit_reason, exited = "sl", True
                elif bar["l"] <= sl_px:
                    exit_reason, exited = "sl", True
                elif bar["h"] >= tp_px:
                    exit_reason, exited = "tp", True
            else:
                if bar["h"] >= sl_px and bar["l"] <= tp_px:
                    exit_reason, exited = "sl", True
                elif bar["h"] >= sl_px:
                    exit_reason, exited = "sl", True
                elif bar["l"] <= tp_px:
                    exit_reason, exited = "tp", True
            pos["hold"] = pos.get("hold", 0) + 1
            if not exited and (new_session or pos["hold"] >= getattr(self.rcfg, "max_hold_bars", 96)):
                exit_reason, exited = "timeout", True
            if exited:
                hit = exit_reason == "tp"
                ev_key = pos.get("ev_key") or ctx.get("ev_key") or (
                    ctx.get("session"),
                    ctx.get("spread_band"),
                    ctx.get("rv_band"),
                )
                self._get_ev_manager(ev_key).update(bool(hit))
            else:
                still.append(pos)
        self.calib_positions = still

    def _maybe_enter_trade(
        self,
        *,
        bar: Dict[str, Any],
        bar_input: Dict[str, Any],
        ctx: Dict[str, Any],
        atr14: float,
        adx14: float,
        or_h: Optional[float],
        or_l: Optional[float],
        mode: str,
        pip_size_value: float,
        calibrating: bool,
    ) -> None:
        self.stg.on_bar(bar_input)
        pending = getattr(self.stg, "_pending_signal", None)
        if pending is None:
            self.debug_counts["no_breakout"] += 1
            self._append_debug_record("no_breakout", ts=self._last_timestamp)
            return
        if self._current_date and self._current_date in self.daily:
            self.daily[self._current_date]["breakouts"] += 1
        ctx_dbg = self._build_ctx(
            bar,
            bar_input["atr14"],
            adx14,
            or_h if or_h == or_h else None,
            or_l if or_l == or_l else None,
        )
        gate_allowed, gate_reason = self._call_strategy_gate(
            ctx_dbg,
            pending,
            ts=self._last_timestamp,
            side=pending.get("side") if isinstance(pending, dict) else None,
        )
        if not gate_allowed:
            self.debug_counts["gate_block"] += 1
            if self._current_date and self._current_date in self.daily:
                self.daily[self._current_date]["gate_block"] += 1
            reason_stage = None
            or_ratio = None
            min_or_ratio = None
            rv_band = None
            if gate_reason:
                reason_stage = gate_reason.get("stage")
                or_ratio = gate_reason.get("or_atr_ratio")
                min_or_ratio = gate_reason.get("min_or_atr_ratio")
                rv_band = gate_reason.get("rv_band")
            self._append_debug_record(
                "strategy_gate",
                ts=self._last_timestamp,
                side=pending.get("side") if isinstance(pending, dict) else None,
                reason_stage=reason_stage,
                or_atr_ratio=or_ratio,
                min_or_atr_ratio=min_or_ratio,
                rv_band=rv_band,
                allow_low_rv=ctx_dbg.get("allow_low_rv"),
            )
            return
        if not pass_gates(ctx_dbg):
            self.debug_counts["gate_block"] += 1
            if self._current_date and self._current_date in self.daily:
                self.daily[self._current_date]["gate_block"] += 1
            self._append_debug_record(
                "gate_block",
                ts=self._last_timestamp,
                side=pending.get("side") if isinstance(pending, dict) else None,
                rv_band=ctx_dbg.get("rv_band"),
                spread_band=ctx_dbg.get("spread_band"),
                or_atr_ratio=ctx_dbg.get("or_atr_ratio"),
                reason="router_gate",
            )
            return
        if self._current_date and self._current_date in self.daily:
            self.daily[self._current_date]["gate_pass"] += 1
        ev_mgr_dbg = self._get_ev_manager(
            ctx_dbg.get(
                "ev_key",
                (
                    ctx_dbg.get("session"),
                    ctx_dbg.get("spread_band"),
                    ctx_dbg.get("rv_band"),
                ),
            )
        )
        threshold_lcb = self.rcfg.threshold_lcb_pip
        threshold_lcb = self._call_ev_threshold(
            ctx_dbg,
            pending,
            threshold_lcb,
            ts=self._last_timestamp,
            side=pending.get("side") if isinstance(pending, dict) else None,
        )
        ctx_dbg["threshold_lcb_pip"] = threshold_lcb
        ev_lcb = (
            ev_mgr_dbg.ev_lcb_oco(
                pending["tp_pips"],
                pending["sl_pips"],
                ctx_dbg["cost_pips"],
            )
            if (pending and not calibrating)
            else 1e9
        )
        ev_bypass = False
        if not calibrating and ev_lcb < threshold_lcb:
            if self._warmup_left > 0:
                ev_bypass = True
                self.debug_counts["ev_bypass"] += 1
            else:
                self.debug_counts["ev_reject"] += 1
                if self._current_date and self._current_date in self.daily:
                    self.daily[self._current_date]["ev_reject"] += 1
                self._append_debug_record(
                    "ev_reject",
                    ts=self._last_timestamp,
                    side=pending.get("side") if isinstance(pending, dict) else None,
                    ev_lcb=ev_lcb,
                    threshold_lcb=threshold_lcb,
                    cost_pips=ctx_dbg.get("cost_pips"),
                    tp_pips=pending.get("tp_pips") if isinstance(pending, dict) else None,
                    sl_pips=pending.get("sl_pips") if isinstance(pending, dict) else None,
                )
                return
        else:
            if self._current_date and self._current_date in self.daily:
                self.daily[self._current_date]["ev_pass"] += 1
        ctx_dbg["ev_lcb"] = ev_lcb
        ctx_dbg["threshold_lcb"] = threshold_lcb
        ctx_dbg["ev_pass"] = not ev_bypass
        slip_cap = ctx_dbg.get("slip_cap_pip", self.rcfg.slip_cap_pip)
        if ctx_dbg.get("expected_slip_pip", 0.0) > slip_cap:
            self.debug_counts["gate_block"] += 1
            if self._current_date and self._current_date in self.daily:
                self.daily[self._current_date]["gate_block"] += 1
            self._append_debug_record(
                "slip_cap",
                ts=self._last_timestamp,
                side=pending.get("side") if isinstance(pending, dict) else None,
                expected_slip_pip=ctx_dbg.get("expected_slip_pip"),
                slip_cap_pip=slip_cap,
            )
            return
        if not ev_bypass and not calibrating:
            p_lcb = ev_mgr_dbg.p_lcb()
            b = pending["tp_pips"] / max(pending["sl_pips"], 1e-9)
            f_star = max(0.0, p_lcb - (1.0 - p_lcb) / b)
            kelly_fraction = 0.25
            mult = min(5.0, kelly_fraction * f_star)
            risk_amt = self.equity * (0.25 / 100.0)
            base = max(
                0.0,
                risk_amt / max(10.0 * pending["sl_pips"], 1e-9),
            )
            qty_dbg = max(
                0.0,
                min(
                    base * mult,
                    (self.equity * (0.5 / 100.0)) / (10.0 * pending["sl_pips"]),
                    5.0,
                ),
            )
            if qty_dbg <= 0:
                self.debug_counts["zero_qty"] += 1
                return
        intents = list(self.stg.signals())
        if not intents:
            self.debug_counts["gate_block"] += 1
            return
        if self._warmup_left > 0:
            self._warmup_left -= 1
        intent = intents[0]
        spec = OrderSpec(
            side=intent.side,
            entry=intent.price,
            tp_pips=intent.oco["tp_pips"],
            sl_pips=intent.oco["sl_pips"],
            trail_pips=intent.oco.get("trail_pips", 0.0),
            slip_cap_pip=ctx["slip_cap_pip"],
        )
        fill_engine = self.fill_engine_c if mode == "conservative" else self.fill_engine_b
        result = fill_engine.simulate(
            {
                "o": bar["o"],
                "h": bar["h"],
                "l": bar["l"],
                "c": bar["c"],
                "pip": pip_size_value,
                "spread": bar["spread"],
            },
            spec,
        )
        if not result.get("fill"):
            return
        trade_ctx_snapshot: Dict[str, Any] = {
            "session": ctx_dbg.get("session", ctx.get("session")),
            "rv_band": ctx_dbg.get("rv_band", ctx.get("rv_band")),
            "spread_band": ctx_dbg.get("spread_band", ctx.get("spread_band")),
            "or_atr_ratio": ctx_dbg.get("or_atr_ratio", ctx.get("or_atr_ratio")),
            "min_or_atr_ratio": ctx_dbg.get("min_or_atr_ratio", ctx.get("min_or_atr_ratio")),
            "ev_lcb": ctx_dbg.get("ev_lcb"),
            "threshold_lcb": ctx_dbg.get("threshold_lcb"),
            "ev_pass": ctx_dbg.get("ev_pass"),
            "expected_slip_pip": ctx.get("expected_slip_pip", 0.0),
            "cost_base": ctx.get("base_cost_pips", ctx.get("cost_pips", 0.0)),
        }
        if "zscore" in bar_input:
            trade_ctx_snapshot["zscore"] = bar_input["zscore"]
        if "exit_px" in result:
            entry_px = result["entry_px"]
            exit_px = result["exit_px"]
            exit_reason = result.get("exit_reason")
            if calibrating:
                hit = exit_reason == "tp"
                ev_key = ctx.get("ev_key") or (
                    ctx.get("session"),
                    ctx.get("spread_band"),
                    ctx.get("rv_band"),
                )
                self._get_ev_manager(ev_key).update(bool(hit))
                return
            qty_sample, slip_actual = self._update_slip_learning(
                order=intent,
                actual_price=entry_px,
                intended_price=intent.price,
                ctx=ctx,
            )
            self._finalize_trade(
                exit_ts=bar.get("timestamp"),
                entry_ts=bar.get("timestamp"),
                side=intent.side,
                entry_px=entry_px,
                exit_px=exit_px,
                exit_reason=exit_reason,
                ctx_snapshot=trade_ctx_snapshot,
                ctx=ctx,
                qty_sample=qty_sample,
                slip_actual=slip_actual,
                ev_key=ctx.get("ev_key"),
                tp_pips=spec.tp_pips,
                sl_pips=spec.sl_pips,
                debug_stage="trade",
                debug_extra={
                    "tp_pips": spec.tp_pips,
                    "sl_pips": spec.sl_pips,
                },
            )
            return
        entry_px = result.get("entry_px")
        tp_px = intent.price + (
            spec.tp_pips * pip_size_value if intent.side == "BUY" else -spec.tp_pips * pip_size_value
        )
        sl_px0 = intent.price - (
            spec.sl_pips * pip_size_value if intent.side == "BUY" else -spec.sl_pips * pip_size_value
        )
        if calibrating:
            self.calib_positions.append(
                {
                    "side": intent.side,
                    "entry_px": entry_px,
                    "tp_px": tp_px,
                    "sl_px": sl_px0,
                    "ev_key": ctx.get("ev_key"),
                    "hold": 0,
                }
            )
            return
        _, entry_slip_pip = self._update_slip_learning(
            order=intent,
            actual_price=entry_px,
            intended_price=intent.price,
            ctx=ctx,
        )
        self.pos = {
            "side": intent.side,
            "entry_px": entry_px,
            "tp_px": tp_px,
            "sl_px": sl_px0,
            "tp_pips": spec.tp_pips,
            "sl_pips": spec.sl_pips,
            "trail_pips": spec.trail_pips,
            "hh": bar["h"],
            "ll": bar["l"],
            "ev_key": ctx.get("ev_key"),
            "qty": getattr(intent, "qty", 1.0) or 1.0,
            "expected_slip_pip": ctx.get("expected_slip_pip", 0.0),
            "entry_slip_pip": entry_slip_pip,
            "hold": 0,
            "entry_ts": bar.get("timestamp"),
            "ctx_snapshot": dict(trade_ctx_snapshot),
        }

    def _record_trade_metrics(self, pnl_pips: float, hit: bool) -> None:
        self.metrics.record_trade(pnl_pips, hit)

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
                "last_timestamp": self._last_timestamp,
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
            "runtime": {
                "warmup_left": self._warmup_left,
                "day_count": self._day_count,
                "current_date": self._current_date,
                "last_session": self._last_session,
            },
        }
        return state

    def load_state(self, state: Dict[str, Any]) -> None:
        try:
            meta = state.get("meta", {})
            # Optionally check fingerprint compatibility
            try:
                fp_state = meta.get("config_fingerprint")
                fp_now = self._config_fingerprint()
                if fp_state and fp_state != fp_now:
                    msg = f"state config_fingerprint mismatch (state={fp_state}, current={fp_now})"
                    # record to debug metrics for downstream visibility
                    try:
                        self.metrics.debug.setdefault("warnings", []).append(msg)
                    except Exception:
                        pass
                    # also print a lightweight warning to stderr for operators
                    try:
                        import sys as _sys
                        print(f"[runner] WARNING: {msg}", file=_sys.stderr)
                    except Exception:
                        pass
            except Exception:
                pass
            if meta.get("last_timestamp"):
                self._last_timestamp = meta.get("last_timestamp")
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
            runtime = state.get("runtime", {})
            if "warmup_left" in runtime:
                try:
                    self._warmup_left = max(0, int(runtime.get("warmup_left", self._warmup_left)))
                except Exception:
                    pass
            if "day_count" in runtime:
                try:
                    self._day_count = max(0, int(runtime.get("day_count", self._day_count)))
                except Exception:
                    pass
            if runtime.get("current_date"):
                self._current_date = runtime.get("current_date")
            if runtime.get("last_session"):
                self._last_session = runtime.get("last_session")
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

    def _apply_ev_profile(self) -> None:
        if not self.ev_profile:
            return

        self._ev_profile_lookup = {}
        global_profile = self.ev_profile.get("global", {})
        seed_global = global_profile.get("recent") or global_profile.get("long_term")
        if seed_global:
            try:
                self.ev_global.alpha = float(seed_global.get("alpha_avg", self.ev_global.alpha))
                self.ev_global.beta = float(seed_global.get("beta_avg", self.ev_global.beta))
            except Exception:
                pass

        buckets = self.ev_profile.get("buckets", [])
        for entry in buckets:
            bucket_info = entry.get("bucket", {})
            try:
                key = (
                    bucket_info["session"],
                    bucket_info["spread_band"],
                    bucket_info["rv_band"],
                )
            except KeyError:
                continue

            if key not in self.ev_buckets:
                self.ev_buckets[key] = BetaBinomialEV(conf_level=self.ev_global.conf_level,
                                                      decay=self.ev_global.decay,
                                                      prior_alpha=self.ev_global.prior_alpha,
                                                      prior_beta=self.ev_global.prior_beta)

            stats = entry.get("recent") or entry.get("long_term")
            if stats:
                try:
                    self.ev_buckets[key].alpha = float(stats.get("alpha_avg", self.ev_buckets[key].alpha))
                    self.ev_buckets[key].beta = float(stats.get("beta_avg", self.ev_buckets[key].beta))
                except Exception:
                    pass

            long_term = entry.get("long_term") or {}
            recent = entry.get("recent") or {}
            self._ev_profile_lookup[key] = {
                "long_term": long_term,
                "recent": recent,
            }

    def _build_ctx(self, bar: Dict[str, Any], atr14: float, adx14: float, or_h: Optional[float], or_l: Optional[float]) -> Dict[str, Any]:
        ps = pip_size(self.symbol)
        spread_pips = bar["spread"] / ps  # assume spread is price units; convert to pips
        # OR quality
        or_ratio = 0.0
        if or_h is not None and or_l is not None and atr14 and atr14 > 0:
            or_ratio = (or_h - or_l) / (atr14)

        sess = self._session_of_ts(bar.get("timestamp", ""))
        rv_val = realized_vol(self.window, n=12)
        if rv_val is None:
            rv_val = 0.0
        else:
            try:
                rv_val = float(rv_val)
            except (TypeError, ValueError):
                rv_val = 0.0
            else:
                if math.isnan(rv_val):
                    rv_val = 0.0

        ctx = {
            "session": sess,
            "spread_band": self._band_spread(spread_pips),
            "rv_band": self._band_rv(rv_val, sess),
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
            "base_cost_pips": spread_pips,
            "equity": self.equity,
            "pip_value": 10.0,  # placeholder; typically derived from notional
            "sizing_cfg": {"risk_per_trade_pct": 0.25, "kelly_fraction": 0.25, "units_cap": 5.0, "max_trade_loss_pct": 0.5},
        }
        if self.rcfg.allowed_sessions:
            ctx["allowed_sessions"] = self.rcfg.allowed_sessions
        key = self._ev_key(ctx["session"], ctx["spread_band"], ctx["rv_band"])
        ctx["ev_key"] = key
        ctx["ev_oco"] = self._get_ev_manager(key)
        if key in self._ev_profile_lookup:
            ctx["ev_profile_stats"] = self._ev_profile_lookup[key]
        # Expected slip cost derived from learnt coefficients (per spread band)
        expected_slip = 0.0
        if getattr(self.rcfg, "include_expected_slip", False):
            band = ctx["spread_band"]
            coeff = float(self.slip_a.get(band, self.rcfg.slip_curve.get(band, {}).get("a", 0.0)))
            intercept = float(self.rcfg.slip_curve.get(band, {}).get("b", 0.0))
            qty_est = self.qty_ewma.get(band, 0.0)
            if qty_est <= 0.0:
                qty_est = 1.0
            expected_slip = max(0.0, coeff * qty_est + intercept)
        ctx["expected_slip_pip"] = expected_slip
        ctx["cost_pips"] = ctx["base_cost_pips"] + expected_slip
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

    def run_partial(self, bars: List[Dict[str, Any]], mode: str = "conservative") -> Metrics:
        ps = pip_size(self.symbol)
        for bar in bars:
            if not validate_bar(bar):
                continue
            new_session, session, calibrating = self._update_daily_state(bar)
            bar_input, ctx, atr14, adx14, or_h, or_l = self._compute_features(
                bar,
                session=session,
                new_session=new_session,
                calibrating=calibrating,
            )
            if self._handle_active_position(
                bar=bar,
                ctx=ctx,
                mode=mode,
                pip_size_value=ps,
                new_session=new_session,
            ):
                continue
            self._resolve_calibration_positions(
                bar=bar,
                ctx=ctx,
                new_session=new_session,
                calibrating=calibrating,
            )
            self._maybe_enter_trade(
                bar=bar,
                bar_input=bar_input,
                ctx=ctx,
                atr14=atr14,
                adx14=adx14,
                or_h=or_h,
                or_l=or_l,
                mode=mode,
                pip_size_value=ps,
                calibrating=calibrating,
            )

        self.metrics.records = list(self.records)
        if self.daily:
            self.metrics.daily = dict(self.daily)

        if self.debug:
            self.metrics.debug.update(self.debug_counts)
            if self.debug_sample_limit:
                self.metrics.records.extend(self.debug_records)
            if self.daily:
                self.metrics.daily = dict(self.daily)
        return self.metrics

    def run(self, bars: List[Dict[str, Any]], mode: str = "conservative") -> Metrics:
        """Run a full batch simulation resetting runtime state first."""
        self._reset_runtime_state()
        self._ev_profile_lookup = {}
        self._apply_ev_profile()
        return self.run_partial(bars, mode=mode)
