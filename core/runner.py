"""
Backtest/Replay Runner (skeleton)
- Validates 5m OHLC bars (minimal checks)
- Builds features and router context
- Runs DayORB5m strategy and simulates fills
- Updates EV estimators and collects simple metrics

NOTE: Placeholder thresholds and simplified assumptions to keep dependencies minimal.
"""
from __future__ import annotations
from typing import Any, Callable, ClassVar, Dict, List, Mapping, Optional, Tuple, Set, Union
from collections import deque
import json
import hashlib
import math
from datetime import datetime, timezone, timedelta
from dataclasses import asdict, dataclass, field

from strategies.day_orb_5m import DayORB5m
from core.strategy_api import Strategy
from core.feature_store import (
    atr as calc_atr,
    adx as calc_adx,
    opening_range,
    realized_vol,
    micro_zscore as calc_micro_zscore,
    micro_trend as calc_micro_trend,
    mid_price as calc_mid_price,
    trend_score as calc_trend_score,
    pullback as calc_pullback,
)
from core.fill_engine import ConservativeFill, BridgeFill, OrderSpec, SameBarPolicy
from core.ev_gate import BetaBinomialEV, TLowerEV
from core.pips import pip_size, price_to_pips, pip_value as calc_pip_value
from core.sizing import SizingConfig, compute_qty_from_ctx
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


def _coerce_same_bar_policy(value: Union[str, SameBarPolicy]) -> SameBarPolicy:
    if isinstance(value, SameBarPolicy):
        return value
    if value is None:
        raise ValueError("same-bar policy cannot be None")
    policy_key = str(value).strip().lower()
    for policy in SameBarPolicy:
        if policy_key in (policy.value, policy.name.lower()):
            return policy
    raise ValueError(f"Unknown same-bar policy '{value}'")


@dataclass
class Metrics:
    trades: int = 0
    wins: int = 0
    total_pips: float = 0.0
    trade_returns: List[float] = field(default_factory=list)
    equity_curve: List[Tuple[str, float]] = field(default_factory=list)
    records: List[Dict[str, Any]] = field(default_factory=list)
    daily: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    debug: Dict[str, Any] = field(default_factory=dict)
    runtime: Dict[str, Any] = field(default_factory=dict)
    starting_equity: float = 0.0
    _equity_seed: Optional[Tuple[str, float]] = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self.starting_equity = float(self.starting_equity)

    @staticmethod
    def _normalise_timestamp(timestamp: Any) -> Tuple[str, Optional[datetime]]:
        if isinstance(timestamp, datetime):
            dt = timestamp
        else:
            ts_str = "unknown" if timestamp is None else str(timestamp)
            iso_value = ts_str
            if ts_str.endswith("Z"):
                iso_value = ts_str[:-1] + "+00:00"
            try:
                dt = datetime.fromisoformat(iso_value)
            except ValueError:
                return ts_str, None
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc)
        else:
            dt = dt.replace(tzinfo=timezone.utc)
        ts_out = dt.replace(tzinfo=None).isoformat() + "Z"
        return ts_out, dt

    @staticmethod
    def _format_timestamp(dt: datetime) -> str:
        return dt.replace(tzinfo=None).isoformat() + "Z"

    def record_trade(
        self,
        pnl_pips: float,
        hit: bool,
        *,
        timestamp: Any,
        pnl_value: Optional[float] = None,
    ) -> None:
        pnl_val = float(pnl_pips)
        pnl_equity = float(pnl_value) if pnl_value is not None else pnl_val
        self.trades += 1
        self.total_pips += pnl_val
        if hit:
            self.wins += 1
        self.trade_returns.append(pnl_equity)
        ts_value, dt_value = self._normalise_timestamp(timestamp)
        if self._equity_seed is None:
            seed_ts = ts_value
            if dt_value is not None:
                seed_ts = self._format_timestamp(dt_value - timedelta(microseconds=1))
            self._equity_seed = (seed_ts, self.starting_equity)
        last_equity = (
            self.equity_curve[-1][1]
            if self.equity_curve
            else self._equity_seed[1]
            if self._equity_seed
            else self.starting_equity
        )
        new_equity = last_equity + pnl_equity
        self.equity_curve.append((ts_value, new_equity))

    def as_dict(self):
        win_rate: Optional[float]
        if self.trades:
            win_rate = self.wins / float(self.trades)
        else:
            win_rate = None

        curve: List[List[Any]] = []
        if self._equity_seed is not None:
            curve.append([self._equity_seed[0], self._equity_seed[1]])
        curve.extend([[ts, equity] for ts, equity in self.equity_curve])

        data = {
            "trades": self.trades,
            "wins": self.wins,
            "win_rate": win_rate,
            "total_pips": self.total_pips,
            "sharpe": self._compute_sharpe(),
            "max_drawdown": self._compute_max_drawdown(),
            "equity_curve": curve,
        }
        if self.runtime:
            data["runtime"] = self.runtime
        return data

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
        values: List[float] = []
        if self._equity_seed is not None:
            values.append(self._equity_seed[1])
        values.extend(point[1] for point in self.equity_curve)
        if not values:
            return None
        peak = values[0]
        max_drawdown = 0.0
        for equity in values:
            if equity > peak:
                peak = equity
            drawdown = equity - peak
            if drawdown < max_drawdown:
                max_drawdown = drawdown
        return max_drawdown


@dataclass
class ExitDecision:
    exited: bool
    exit_px: Optional[float]
    exit_reason: Optional[str]
    updated_pos: Optional[Dict[str, Any]]


@dataclass
class FeatureBundle:
    bar_input: Dict[str, Any]
    ctx: Dict[str, Any]
    atr14: float
    adx14: float
    or_high: Optional[float]
    or_low: Optional[float]
    realized_vol: float
    micro_zscore: float = 0.0
    micro_trend: float = 0.0
    mid_price: float = 0.0
    trend_score: float = 0.0
    pullback: float = 0.0


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
    # Fill engine configuration
    fill_same_bar_policy_conservative: Union[str, SameBarPolicy] = SameBarPolicy.SL_FIRST.value
    fill_same_bar_policy_bridge: Union[str, SameBarPolicy] = SameBarPolicy.PROBABILISTIC.value
    fill_bridge_lambda: float = 0.35
    fill_bridge_drift_scale: float = 2.5

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

    def build_sizing_cfg(self) -> Dict[str, float]:
        cfg = SizingConfig()
        numeric_risk: Optional[float]
        try:
            numeric_risk = float(self.risk_per_trade_pct)
        except (TypeError, ValueError):
            numeric_risk = None
        if numeric_risk is not None and numeric_risk > 0:
            cfg.risk_per_trade_pct = numeric_risk
        return asdict(cfg)

    def resolve_same_bar_policy(self, mode: str) -> SameBarPolicy:
        if mode not in ("conservative", "bridge"):
            raise ValueError(f"Unknown fill mode '{mode}' for same-bar policy resolution")
        value: Union[str, SameBarPolicy]
        if mode == "conservative":
            value = self.fill_same_bar_policy_conservative
        else:
            value = self.fill_same_bar_policy_bridge
        return _coerce_same_bar_policy(value)


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
        "ev_bypass": (
            "ts",
            "side",
            "ev_lcb",
            "threshold_lcb",
            "warmup_left",
            "warmup_total",
            "cost_pips",
            "tp_pips",
            "sl_pips",
        ),
        "ev_threshold_error": ("ts", "side", "base_threshold", "error"),
        "trade": ("ts", "side", "tp_pips", "sl_pips", "cost_pips", "slip_est", "slip_real", "exit", "pnl_pips"),
        "trade_exit": ("ts", "side", "cost_pips", "slip_est", "slip_real", "exit", "pnl_pips"),
    }
    DAILY_COUNT_FIELDS: ClassVar[Tuple[str, ...]] = (
        "breakouts",
        "gate_pass",
        "gate_block",
        "ev_pass",
        "ev_reject",
        "fills",
        "wins",
    )
    DAILY_FLOAT_FIELDS: ClassVar[Tuple[str, ...]] = (
        "pnl_pips",
        "slip_est",
        "slip_real",
    )
    _DAILY_FLOAT_FIELD_SET: ClassVar[Set[str]] = set(DAILY_FLOAT_FIELDS)

    def __init__(self, equity: float, symbol: str, runner_cfg: Optional[RunnerConfig] = None,
                 debug: bool = False, debug_sample_limit: int = 0,
                 strategy_cls: Optional[type[Strategy]] = None,
                 ev_profile: Optional[Dict[str, Any]] = None):
        self.equity = float(equity)
        self._equity_live = float(equity)
        self.symbol = symbol
        self.rcfg = runner_cfg or RunnerConfig()
        self.debug = debug
        self.debug_sample_limit = max(0, int(debug_sample_limit))
        self.strategy_cls = strategy_cls or DayORB5m
        self.ev_profile = ev_profile or {}
        self._init_ev_state()
        cons_policy = self.rcfg.resolve_same_bar_policy("conservative")
        bridge_policy = self.rcfg.resolve_same_bar_policy("bridge")
        self.fill_engine_c = ConservativeFill(cons_policy)
        self.fill_engine_b = BridgeFill(
            same_bar_policy=bridge_policy,
            lam=float(self.rcfg.fill_bridge_lambda),
            drift_scale=float(self.rcfg.fill_bridge_drift_scale),
        )
        self._reset_runtime_state()
        self._ev_profile_lookup: Dict[tuple, Dict[str, Any]] = {}
        # Slip/size expectation tracking
        self._reset_slip_learning()

        # strategy
        self.stg = self.strategy_cls()
        self.stg.on_start(self.rcfg.strategy.as_dict(), [symbol], {})
        self._strategy_gate_hook = self._resolve_strategy_hook("strategy_gate")
        self._ev_threshold_hook = self._resolve_strategy_hook("ev_threshold")
        self._apply_ev_profile()

    def _init_ev_state(self) -> None:
        self.ev_global = BetaBinomialEV(
            conf_level=0.95,
            decay=self.rcfg.ev_decay,
            prior_alpha=self.rcfg.prior_alpha,
            prior_beta=self.rcfg.prior_beta,
        )
        # bucket store for pooled EV
        self.ev_buckets = {}  # type: Dict[tuple, BetaBinomialEV]
        self.ev_var = TLowerEV(conf_level=0.95, decay=self.rcfg.ev_decay)

    def _reset_slip_learning(self) -> None:
        self.slip_a = {
            "narrow": self.rcfg.slip_curve.get("narrow", {}).get("a", 0.0),
            "normal": self.rcfg.slip_curve.get("normal", {}).get("a", 0.0),
            "wide": self.rcfg.slip_curve.get("wide", {}).get("a", 0.0),
        }
        self.qty_ewma = {"narrow": 0.0, "normal": 0.0, "wide": 0.0}

    def _reset_runtime_state(self) -> None:
        self._equity_live = float(self.equity)
        self.metrics = Metrics(starting_equity=self._equity_live)
        self.records: List[Dict[str, Any]] = []
        self.window: List[Dict[str, Any]] = []
        self.session_bars: List[Dict[str, Any]] = []
        self.debug_counts: Dict[str, int] = {key: 0 for key in self.DEBUG_COUNT_KEYS}
        self.debug_records: List[Dict[str, Any]] = []
        self.daily: Dict[str, Dict[str, Any]] = {}
        self._current_daily_entry: Optional[Dict[str, Union[int, float]]] = None
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

    @classmethod
    def _create_daily_entry(cls) -> Dict[str, Union[int, float]]:
        entry: Dict[str, Union[int, float]] = {
            key: 0 for key in cls.DAILY_COUNT_FIELDS
        }
        entry.update({key: 0.0 for key in cls.DAILY_FLOAT_FIELDS})
        return entry

    def _ensure_daily_entry(self, date_str: str) -> Dict[str, Union[int, float]]:
        entry = self.daily.get(date_str)
        if entry is None:
            entry = self._create_daily_entry()
            self.daily[date_str] = entry
        return entry

    def _increment_daily(self, key: str, amount: float = 1.0) -> None:
        entry = getattr(self, "_current_daily_entry", None)
        if entry is None:
            return
        if key in self._DAILY_FLOAT_FIELD_SET:
            entry[key] = float(entry.get(key, 0.0)) + float(amount)
        else:
            entry[key] = int(entry.get(key, 0)) + int(amount)

    def _build_runtime_snapshot(self) -> Dict[str, Any]:
        totals = {
            "ev_pass": 0,
            "ev_reject": 0,
            "fills": 0,
            "slip_real": 0.0,
        }
        for entry in self.daily.values():
            totals["ev_pass"] += int(entry.get("ev_pass", 0))
            totals["ev_reject"] += int(entry.get("ev_reject", 0))
            totals["fills"] += int(entry.get("fills", 0))
            totals["slip_real"] += float(entry.get("slip_real", 0.0))

        runtime: Dict[str, Any] = {
            "ev_pass": totals["ev_pass"],
            "ev_reject": totals["ev_reject"],
            "fills": totals["fills"],
        }
        gate_total = totals["ev_pass"] + totals["ev_reject"]
        exec_health: Dict[str, float] = {}
        if gate_total > 0:
            exec_health["reject_rate"] = totals["ev_reject"] / float(gate_total)
        if totals["fills"] > 0:
            exec_health["slippage_bps"] = totals["slip_real"] / float(totals["fills"])
        if exec_health:
            runtime["execution_health"] = exec_health
        return runtime

    @staticmethod
    def _quantile(values: List[float], q: float) -> Optional[float]:
        if not values:
            return None
        idx = max(0, min(len(values) - 1, int(q * (len(values) - 1))))
        return values[idx]

    def _update_rv_thresholds(self) -> None:
        minimum = max(100, int(self.rcfg.rv_q_lookback_bars * 0.2))
        for session_name in ("TOK", "LDN", "NY"):
            hist = list(self.rv_hist[session_name])
            if len(hist) < minimum:
                continue
            hist_sorted = sorted(hist)
            low = self._quantile(hist_sorted, self.rcfg.rv_q_low)
            high = self._quantile(hist_sorted, self.rcfg.rv_q_high)
            if low is not None and high is not None and low <= high:
                self.rv_thresh[session_name] = (low, high)

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

    @staticmethod
    def _extract_pending_fields(
        pending: Any,
    ) -> Tuple[Optional[str], Optional[float], Optional[float]]:
        def _coerce(value: Any) -> Optional[float]:
            if value is None:
                return None
            try:
                coerced = float(value)
            except (TypeError, ValueError):
                return None
            if not math.isfinite(coerced):
                return None
            return coerced

        if isinstance(pending, Mapping):
            pending_side = pending.get("side")
            tp_pips = pending.get("tp_pips")
            sl_pips = pending.get("sl_pips")
            oco = pending.get("oco")
        else:
            pending_side = getattr(pending, "side", None)
            tp_pips = getattr(pending, "tp_pips", None)
            sl_pips = getattr(pending, "sl_pips", None)
            oco = getattr(pending, "oco", None)

        if tp_pips is None and oco is not None:
            if isinstance(oco, Mapping):
                tp_pips = oco.get("tp_pips")
            else:
                tp_pips = getattr(oco, "tp_pips", None)
        if sl_pips is None and oco is not None:
            if isinstance(oco, Mapping):
                sl_pips = oco.get("sl_pips")
            else:
                sl_pips = getattr(oco, "sl_pips", None)

        return pending_side, _coerce(tp_pips), _coerce(sl_pips)

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
        pip_value_ctx = ctx_snapshot.get("pip_value")
        if pip_value_ctx is None:
            pip_value_ctx = ctx.get("pip_value", 10.0)
        try:
            pip_value_float = float(pip_value_ctx)
        except (TypeError, ValueError):
            pip_value_float = 0.0
        pnl_value = pnl_pips * pip_value_float * float(qty_sample)
        self._equity_live += pnl_value
        self._record_trade_metrics(
            pnl_pips,
            hit,
            timestamp=exit_ts,
            pnl_value=pnl_value,
        )
        self._increment_daily("fills")
        if hit:
            self._increment_daily("wins")
        self._increment_daily("pnl_pips", pnl_pips)
        self._increment_daily("slip_est", est_slip_used)
        self._increment_daily("slip_real", slip_actual)
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
        if isinstance(date_str, str):
            new_day = date_str != self._current_date
            self._current_date = date_str
            if new_day:
                self._day_count += 1
            self._current_daily_entry = self._ensure_daily_entry(date_str)
            if new_day and self.rcfg.rv_qcalib_enabled:
                self._update_rv_thresholds()
        else:
            self._current_date = None
            self._current_daily_entry = None
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
    ) -> FeatureBundle:
        self.window.append({k: bar[k] for k in ("o", "h", "l", "c")})
        if len(self.window) > 200:
            self.window.pop(0)
        if new_session:
            self.session_bars = []
        self.session_bars.append({k: bar[k] for k in ("o", "h", "l", "c")})
        rv_hist_value = 0.0
        try:
            rv_lookback = 12
            rv_window = (
                self.window[-(rv_lookback + 1) :]
                if len(self.window) >= rv_lookback + 1
                else None
            )
            rv_computed = realized_vol(rv_window, n=rv_lookback)
        except Exception:
            rv_computed = None
        if rv_computed is not None:
            try:
                rv_hist_value = float(rv_computed)
            except (TypeError, ValueError):
                rv_hist_value = 0.0
        try:
            self.rv_hist[session].append(rv_hist_value)
        except Exception:
            pass
        atr14 = calc_atr(self.window[-15:]) if len(self.window) >= 15 else float("nan")
        adx14 = calc_adx(self.window[-15:]) if len(self.window) >= 15 else float("nan")
        or_h, or_l = opening_range(self.session_bars, n=self.rcfg.or_n)
        micro_z = calc_micro_zscore(self.window)
        micro_tr = calc_micro_trend(self.window)
        mid_px = calc_mid_price(bar)
        trend_val = calc_trend_score(self.window)
        pullback_val = calc_pullback(self.session_bars)

        def _sanitize(value: Any) -> float:
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                return 0.0
            if not math.isfinite(numeric):
                return 0.0
            return numeric

        bar_input: Dict[str, Any] = {
            "o": bar["o"],
            "h": bar["h"],
            "l": bar["l"],
            "c": bar["c"],
            "atr14": atr14 if atr14 == atr14 else 0.0,
            "window": self.session_bars[: self.rcfg.or_n],
            "new_session": new_session,
        }
        bar_input.update(
            micro_zscore=_sanitize(micro_z),
            micro_trend=_sanitize(micro_tr),
            mid_price=_sanitize(mid_px),
            trend_score=_sanitize(trend_val),
            pullback=_sanitize(pullback_val),
        )
        if "zscore" in bar:
            zscore_val = bar["zscore"]
            try:
                zscore_val = float(zscore_val)
            except (TypeError, ValueError):
                pass
            bar_input["zscore"] = zscore_val
        rv_for_ctx = rv_hist_value
        if math.isnan(rv_for_ctx):
            rv_for_ctx = 0.0
        ctx = self._build_ctx(
            bar=bar,
            session=session,
            atr14=bar_input["atr14"],
            or_h=or_h if or_h == or_h else None,
            or_l=or_l if or_l == or_l else None,
            realized_vol_value=rv_for_ctx,
        )
        if calibrating:
            ctx["threshold_lcb_pip"] = -1e9
            ctx["calibrating"] = True
        self.stg.cfg["ctx"] = dict(ctx)
        return FeatureBundle(
            bar_input=bar_input,
            ctx=ctx,
            atr14=atr14,
            adx14=adx14,
            or_high=or_h if or_h == or_h else None,
            or_low=or_l if or_l == or_l else None,
            realized_vol=rv_for_ctx,
            micro_zscore=bar_input["micro_zscore"],
            micro_trend=bar_input["micro_trend"],
            mid_price=bar_input["mid_price"],
            trend_score=bar_input["trend_score"],
            pullback=bar_input["pullback"],
        )

    def _compute_exit_decision(
        self,
        *,
        pos: Mapping[str, Any],
        bar: Mapping[str, Any],
        mode: str,
        pip_size_value: float,
        new_session: bool,
    ) -> ExitDecision:
        updated_pos: Dict[str, Any] = dict(pos)
        side = updated_pos["side"]
        entry_px = updated_pos["entry_px"]
        tp_px = updated_pos["tp_px"]
        sl_px = updated_pos["sl_px"]
        trail_pips = float(updated_pos.get("trail_pips", 0.0) or 0.0)
        direction = 1.0 if side == "BUY" else -1.0

        if trail_pips > 0.0:
            if side == "BUY":
                updated_pos["hh"] = max(updated_pos.get("hh", entry_px), bar["h"])
                new_sl = updated_pos["hh"] - trail_pips * pip_size_value
                sl_px = max(sl_px, new_sl)
            else:
                updated_pos["ll"] = min(updated_pos.get("ll", entry_px), bar["l"])
                new_sl = updated_pos["ll"] + trail_pips * pip_size_value
                sl_px = min(sl_px, new_sl)
            updated_pos["sl_px"] = sl_px

        exit_px: Optional[float] = None
        exit_reason: Optional[str] = None
        sl_hit = bar["l"] <= sl_px if side == "BUY" else bar["h"] >= sl_px
        tp_hit = bar["h"] >= tp_px if side == "BUY" else bar["l"] <= tp_px

        if sl_hit and tp_hit:
            if mode == "conservative":
                exit_px, exit_reason = sl_px, "sl"
            else:
                rng = max(bar["h"] - bar["l"], pip_size_value)
                drift = direction * (bar["c"] - bar["o"]) / rng if rng > 0 else 0.0
                d_tp = max(((tp_px - entry_px) * direction) / pip_size_value, 1e-9)
                d_sl = max(((entry_px - sl_px) * direction) / pip_size_value, 1e-9)
                base = d_sl / (d_tp + d_sl)
                p_tp = min(
                    0.999,
                    max(0.001, 0.65 * base + 0.35 * 0.5 * (1.0 + math.tanh(2.5 * drift))),
                )
                exit_px = p_tp * tp_px + (1 - p_tp) * sl_px
                exit_reason = "tp" if p_tp >= 0.5 else "sl"
            exited = True
        elif sl_hit:
            exit_px, exit_reason, exited = sl_px, "sl", True
        elif tp_hit:
            exit_px, exit_reason, exited = tp_px, "tp", True
        else:
            exited = False

        if not exited:
            hold = updated_pos.get("hold", 0) + 1
            updated_pos["hold"] = hold
            max_hold = getattr(self.rcfg, "max_hold_bars", 96)
            if new_session or hold >= max_hold:
                exit_px = bar["o"]
                exit_reason = "session_end" if new_session else "timeout"
                exited = True

        if exited:
            return ExitDecision(True, exit_px, exit_reason, None)
        return ExitDecision(False, None, None, updated_pos)

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

        current_pos = self.pos
        decision = self._compute_exit_decision(
            pos=current_pos,
            bar=bar,
            mode=mode,
            pip_size_value=pip_size_value,
            new_session=new_session,
        )
        self.pos = decision.updated_pos

        if decision.exited and decision.exit_px is not None:
            qty_sample = current_pos.get("qty", 1.0) or 1.0
            slip_actual = current_pos.get("entry_slip_pip", 0.0)
            self._finalize_trade(
                exit_ts=bar.get("timestamp"),
                entry_ts=current_pos.get("entry_ts"),
                side=current_pos["side"],
                entry_px=current_pos["entry_px"],
                exit_px=decision.exit_px,
                exit_reason=decision.exit_reason,
                ctx_snapshot=current_pos.get("ctx_snapshot", {}),
                ctx=ctx,
                qty_sample=qty_sample,
                slip_actual=slip_actual,
                ev_key=current_pos.get("ev_key"),
                tp_pips=current_pos.get("tp_pips", 0.0),
                sl_pips=current_pos.get("sl_pips", 0.0),
                debug_stage="trade_exit",
            )

        return True

    def _resolve_calibration_positions(
        self,
        *,
        bar: Dict[str, Any],
        ctx: Mapping[str, Any],
        new_session: bool,
        calibrating: bool,
        mode: str,
        pip_size_value: float,
    ) -> None:
        if not self.calib_positions:
            return
        # Continue resolving calibration trades even after the calibration
        # window ends so their outcomes update pooled EV statistics.
        still: List[Dict[str, Any]] = []
        for raw_pos in self.calib_positions:
            normalized = {
                "side": raw_pos["side"],
                "entry_px": raw_pos["entry_px"],
                "tp_px": raw_pos["tp_px"],
                "sl_px": raw_pos["sl_px"],
                "trail_pips": float(raw_pos.get("trail_pips", 0.0) or 0.0),
                "hh": raw_pos.get("hh", raw_pos["entry_px"]),
                "ll": raw_pos.get("ll", raw_pos["entry_px"]),
                "hold": int(raw_pos.get("hold", 0) or 0),
            }
            decision = self._compute_exit_decision(
                pos=normalized,
                bar=bar,
                mode=mode,
                pip_size_value=pip_size_value,
                new_session=new_session,
            )
            ev_key = raw_pos.get("ev_key") or ctx.get("ev_key") or (
                ctx.get("session"),
                ctx.get("spread_band"),
                ctx.get("rv_band"),
            )
            if decision.exited:
                hit = decision.exit_reason == "tp"
                self._get_ev_manager(ev_key).update(bool(hit))
                continue
            updated = decision.updated_pos or normalized
            still.append(
                {
                    "side": updated["side"],
                    "entry_px": updated["entry_px"],
                    "tp_px": updated["tp_px"],
                    "sl_px": updated["sl_px"],
                    "trail_pips": float(updated.get("trail_pips", normalized["trail_pips"])),
                    "hh": updated.get("hh", normalized["hh"]),
                    "ll": updated.get("ll", normalized["ll"]),
                    "hold": int(updated.get("hold", normalized["hold"])),
                    "ev_key": raw_pos.get("ev_key"),
                }
            )
        self.calib_positions = still



    def _maybe_enter_trade(
        self,
        *,
        bar: Dict[str, Any],
        features: FeatureBundle,
        mode: str,
        pip_size_value: float,
        calibrating: bool,
    ) -> None:
        self.stg.on_bar(features.bar_input)
        pending = getattr(self.stg, "_pending_signal", None)
        if pending is None:
            self.debug_counts["no_breakout"] += 1
            self._append_debug_record("no_breakout", ts=self._last_timestamp)
            return
        self._increment_daily("breakouts")
        ctx_dbg = self._evaluate_entry_conditions(
            pending=pending,
            features=features,
        )
        if ctx_dbg is None:
            return
        ev_eval = self._evaluate_ev_threshold(
            ctx_dbg=ctx_dbg,
            pending=pending,
            calibrating=calibrating,
            timestamp=self._last_timestamp,
        )
        if ev_eval is None:
            return
        ev_mgr_dbg, _, _, ev_bypass = ev_eval
        if not self._check_slip_and_sizing(
            ctx_dbg=ctx_dbg,
            pending=pending,
            ev_mgr=ev_mgr_dbg,
            calibrating=calibrating,
            ev_bypass=ev_bypass,
            timestamp=self._last_timestamp,
        ):
            return
        intents = list(self.stg.signals())
        if not intents:
            self.debug_counts["gate_block"] += 1
            return
        intent = intents[0]
        spec = OrderSpec(
            side=intent.side,
            entry=intent.price,
            tp_pips=intent.oco["tp_pips"],
            sl_pips=intent.oco["sl_pips"],
            trail_pips=intent.oco.get("trail_pips", 0.0),
            slip_cap_pip=features.ctx["slip_cap_pip"],
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
            "session": ctx_dbg.get("session", features.ctx.get("session")),
            "rv_band": ctx_dbg.get("rv_band", features.ctx.get("rv_band")),
            "spread_band": ctx_dbg.get("spread_band", features.ctx.get("spread_band")),
            "or_atr_ratio": ctx_dbg.get("or_atr_ratio", features.ctx.get("or_atr_ratio")),
            "min_or_atr_ratio": ctx_dbg.get("min_or_atr_ratio", features.ctx.get("min_or_atr_ratio")),
            "ev_lcb": ctx_dbg.get("ev_lcb"),
            "threshold_lcb": ctx_dbg.get("threshold_lcb"),
            "ev_pass": ctx_dbg.get("ev_pass"),
            "expected_slip_pip": features.ctx.get("expected_slip_pip", 0.0),
            "pip_value": features.ctx.get("pip_value"),
            "cost_base": features.ctx.get(
                "base_cost_pips", features.ctx.get("cost_pips", 0.0)
            ),
        }
        if "zscore" in features.bar_input:
            trade_ctx_snapshot["zscore"] = features.bar_input["zscore"]
        self._process_fill_result(
            intent=intent,
            spec=spec,
            result=result,
            bar=bar,
            ctx=features.ctx,
            ctx_dbg=ctx_dbg,
            trade_ctx_snapshot=trade_ctx_snapshot,
            calibrating=calibrating,
            pip_size_value=pip_size_value,
        )
        if not calibrating and self._warmup_left > 0:
            self._warmup_left -= 1


    def _evaluate_entry_conditions(
        self,
        *,
        pending: Any,
        features: FeatureBundle,
    ) -> Optional[Dict[str, Any]]:
        ctx_dbg = dict(features.ctx)
        pending_side, _, _ = self._extract_pending_fields(pending)
        gate_allowed, gate_reason = self._call_strategy_gate(
            ctx_dbg,
            pending,
            ts=self._last_timestamp,
            side=pending_side,
        )
        if not gate_allowed:
            self.debug_counts["gate_block"] += 1
            self._increment_daily("gate_block")
            reason_stage = None
            or_ratio = None
            min_or_ratio = None
            rv_band = None
            if isinstance(gate_reason, Mapping):
                reason_stage = gate_reason.get("stage")
                or_ratio = gate_reason.get("or_atr_ratio")
                min_or_ratio = gate_reason.get("min_or_atr_ratio")
                rv_band = gate_reason.get("rv_band")
            self._append_debug_record(
                "strategy_gate",
                ts=self._last_timestamp,
                side=pending_side,
                reason_stage=reason_stage,
                or_atr_ratio=or_ratio,
                min_or_atr_ratio=min_or_ratio,
                rv_band=rv_band,
                allow_low_rv=ctx_dbg.get("allow_low_rv"),
            )
            return None
        if not pass_gates(ctx_dbg):
            self.debug_counts["gate_block"] += 1
            self._increment_daily("gate_block")
            self._append_debug_record(
                "gate_block",
                ts=self._last_timestamp,
                side=pending_side,
                rv_band=ctx_dbg.get("rv_band"),
                spread_band=ctx_dbg.get("spread_band"),
                or_atr_ratio=ctx_dbg.get("or_atr_ratio"),
                reason="router_gate",
            )
            return None
        self._increment_daily("gate_pass")
        return ctx_dbg

    def _evaluate_ev_threshold(
        self,
        *,
        ctx_dbg: Dict[str, Any],
        pending: Any,
        calibrating: bool,
        timestamp: Optional[str],
    ) -> Optional[Tuple[Any, float, float, bool]]:
        pending_side, tp_pips, sl_pips = self._extract_pending_fields(pending)
        ev_key = ctx_dbg.get(
            "ev_key",
            (
                ctx_dbg.get("session"),
                ctx_dbg.get("spread_band"),
                ctx_dbg.get("rv_band"),
            ),
        )
        ev_mgr = self._get_ev_manager(ev_key)
        threshold_lcb = self._call_ev_threshold(
            ctx_dbg,
            pending,
            self.rcfg.threshold_lcb_pip,
            ts=timestamp,
            side=pending_side,
        )
        ctx_dbg["threshold_lcb_pip"] = threshold_lcb
        ev_lcb = (
            ev_mgr.ev_lcb_oco(
                float(tp_pips),
                float(sl_pips),
                ctx_dbg["cost_pips"],
            )
            if (tp_pips is not None and sl_pips is not None and not calibrating)
            else 1e9
        )
        ev_bypass = False
        if not calibrating and ev_lcb < threshold_lcb:
            if self._warmup_left > 0:
                ev_bypass = True
                warmup_remaining = int(self._warmup_left)
                self.debug_counts["ev_bypass"] += 1
                self._append_debug_record(
                    "ev_bypass",
                    ts=timestamp,
                    side=pending_side,
                    ev_lcb=ev_lcb,
                    threshold_lcb=threshold_lcb,
                    warmup_left=warmup_remaining,
                    warmup_total=int(self.rcfg.warmup_trades),
                    cost_pips=ctx_dbg.get("cost_pips"),
                    tp_pips=tp_pips,
                    sl_pips=sl_pips,
                )
            else:
                self.debug_counts["ev_reject"] += 1
                self._increment_daily("ev_reject")
                self._append_debug_record(
                    "ev_reject",
                    ts=timestamp,
                    side=pending_side,
                    ev_lcb=ev_lcb,
                    threshold_lcb=threshold_lcb,
                    cost_pips=ctx_dbg.get("cost_pips"),
                    tp_pips=tp_pips,
                    sl_pips=sl_pips,
                )
                return None
        else:
            self._increment_daily("ev_pass")
        ctx_dbg["ev_lcb"] = ev_lcb
        ctx_dbg["threshold_lcb"] = threshold_lcb
        ctx_dbg["ev_pass"] = not ev_bypass
        return ev_mgr, ev_lcb, threshold_lcb, ev_bypass

    def _check_slip_and_sizing(
        self,
        *,
        ctx_dbg: Mapping[str, Any],
        pending: Any,
        ev_mgr: Any,
        calibrating: bool,
        ev_bypass: bool,
        timestamp: Optional[str],
    ) -> bool:
        pending_side, tp_pips, sl_pips = self._extract_pending_fields(pending)
        slip_cap = ctx_dbg.get("slip_cap_pip", self.rcfg.slip_cap_pip)
        expected_slip = ctx_dbg.get("expected_slip_pip", 0.0)
        if expected_slip > slip_cap:
            self.debug_counts["gate_block"] += 1
            self._increment_daily("gate_block")
            self._append_debug_record(
                "slip_cap",
                ts=timestamp,
                side=pending_side,
                expected_slip_pip=expected_slip,
                slip_cap_pip=slip_cap,
            )
            return False
        if not ev_bypass and not calibrating and tp_pips is not None and sl_pips is not None:
            ctx_for_sizing: Dict[str, Any] = dict(ctx_dbg)
            ctx_for_sizing.setdefault("equity", self._equity_live)
            qty_dbg = compute_qty_from_ctx(
                ctx_for_sizing,
                float(sl_pips),
                mode="production",
                tp_pips=float(tp_pips),
                p_lcb=ev_mgr.p_lcb(),
            )
            if qty_dbg <= 0:
                self.debug_counts["zero_qty"] += 1
                return False
        return True

    def _process_fill_result(
        self,
        *,
        intent: Any,
        spec: OrderSpec,
        result: Mapping[str, Any],
        bar: Mapping[str, Any],
        ctx: Mapping[str, Any],
        ctx_dbg: Mapping[str, Any],
        trade_ctx_snapshot: Dict[str, Any],
        calibrating: bool,
        pip_size_value: float,
    ) -> None:
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
                    "trail_pips": spec.trail_pips,
                    "hh": bar["h"],
                    "ll": bar["l"],
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

    def _record_trade_metrics(
        self,
        pnl_pips: float,
        hit: bool,
        *,
        timestamp: Any,
        pnl_value: Optional[float] = None,
    ) -> None:
        self.metrics.record_trade(
            pnl_pips,
            hit,
            timestamp=timestamp,
            pnl_value=pnl_value,
        )

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

    def _build_ctx(
        self,
        *,
        bar: Mapping[str, Any],
        session: str,
        atr14: float,
        or_h: Optional[float],
        or_l: Optional[float],
        realized_vol_value: float,
    ) -> Dict[str, Any]:
        ps = pip_size(self.symbol)
        spread_pips = bar["spread"] / ps  # assume spread is price units; convert to pips

        pip_value_default = 10.0
        pip_value_ctx = pip_value_default

        pip_override_raw = getattr(self.rcfg, "pip_value_override", None)
        try:
            pip_override_value: Optional[float] = (
                float(pip_override_raw) if pip_override_raw is not None else None
            )
        except (TypeError, ValueError):
            pip_override_value = None

        if pip_override_value is not None and pip_override_value > 0.0:
            pip_value_ctx = pip_override_value
        else:
            base_notional_raw = getattr(self.rcfg, "base_notional", None)
            try:
                base_notional_value: Optional[float] = (
                    float(base_notional_raw) if base_notional_raw is not None else None
                )
            except (TypeError, ValueError):
                base_notional_value = None

            if base_notional_value is not None and base_notional_value > 0.0:
                pip_value_ctx = calc_pip_value(self.symbol, base_notional_value)

        or_ratio = 0.0
        if or_h is not None and or_l is not None and atr14 and atr14 > 0:
            or_ratio = (or_h - or_l) / atr14

        ctx = {
            "session": session,
            "spread_band": self._band_spread(spread_pips),
            "rv_band": self._band_rv(realized_vol_value, session),
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
            "equity": self._equity_live,
            "pip_value": pip_value_ctx,
            "sizing_cfg": self.rcfg.build_sizing_cfg(),
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
            features = self._compute_features(
                bar,
                session=session,
                new_session=new_session,
                calibrating=calibrating,
            )
            if self._handle_active_position(
                bar=bar,
                ctx=features.ctx,
                mode=mode,
                pip_size_value=ps,
                new_session=new_session,
            ):
                continue
            self._resolve_calibration_positions(
                bar=bar,
                ctx=features.ctx,
                new_session=new_session,
                calibrating=calibrating,
                mode=mode,
                pip_size_value=ps,
            )
            self._maybe_enter_trade(
                bar=bar,
                features=features,
                mode=mode,
                pip_size_value=ps,
                calibrating=calibrating,
            )

        self.metrics.records = list(self.records)
        if self.daily:
            self.metrics.daily = dict(self.daily)

        self.metrics.runtime = self._build_runtime_snapshot()

        if self.debug:
            self.metrics.debug.update(self.debug_counts)
            if self.debug_sample_limit:
                self.metrics.records.extend(self.debug_records)
            if self.daily:
                self.metrics.daily = dict(self.daily)
        return self.metrics

    def run(self, bars: List[Dict[str, Any]], mode: str = "conservative") -> Metrics:
        """Run a full batch simulation resetting runtime and learning state first.

        The strategy instance itself is reused across runs so strategy-level state
        management should ensure fresh signals per bar when invoking ``run``
        repeatedly.
        """
        self._reset_runtime_state()
        self._init_ev_state()
        self._reset_slip_learning()
        self._ev_profile_lookup = {}
        self._apply_ev_profile()
        return self.run_partial(bars, mode=mode)
