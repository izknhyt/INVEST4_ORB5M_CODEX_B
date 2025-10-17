"""
Backtest/Replay Runner (skeleton)
- Validates 5m OHLC bars (minimal checks)
- Builds features and router context
- Runs DayORB5m strategy and simulates fills
- Updates EV estimators and collects simple metrics

NOTE: Placeholder thresholds and simplified assumptions to keep dependencies minimal.
"""
from __future__ import annotations
from typing import Any, Callable, ClassVar, Dict, Iterable, List, Mapping, Optional, Tuple, Set, Union
from collections import deque
from copy import deepcopy
import hashlib
import math
from datetime import datetime, timezone, timedelta
from dataclasses import asdict, dataclass, field

from strategies.day_orb_5m import DayORB5m
from core.strategy_api import Strategy
from core.fill_engine import ConservativeFill, BridgeFill, OrderSpec, SameBarPolicy
from core.ev_gate import BetaBinomialEV, TLowerEV
from core.pips import pip_size, price_to_pips, pip_value as calc_pip_value
from core.sizing import SizingConfig, compute_qty_from_ctx
from core.runner_entry import (
    EntryGate,
    EVGate,
    SizingGate,
    EntryEvaluation,
    EVEvaluation,
    SizingEvaluation,
    TradeContextSnapshot,
    build_trade_context_snapshot,
    EntryContext,
    EVContext,
    SizingContext,
)
from core.runner_execution import ExitDecision, RunnerExecutionManager
from core.runner_lifecycle import RunnerLifecycleManager
from core.runner_state import ActivePositionState, CalibrationPositionState, PositionState
from core.runner_features import FeatureBundle, FeaturePipeline


def _normalise_timeframes(values: Optional[Iterable[Any]]) -> Tuple[str, ...]:
    if values is None:
        return ("5m",)
    normalised = []
    for value in values:
        text = str(value).strip().lower()
        if text:
            normalised.append(text)
    if not normalised:
        return ("5m",)
    return tuple(dict.fromkeys(normalised))


def validate_bar(bar: Dict[str, Any], allowed_timeframes: Optional[Iterable[Any]] = None) -> bool:
    req = ["timestamp", "symbol", "tf", "o", "h", "l", "c", "v", "spread"]
    if not all(k in bar for k in req):
        return False
    allowed = _normalise_timeframes(allowed_timeframes)
    tf_value = str(bar.get("tf", "")).strip().lower()
    if tf_value not in allowed:
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
    wins: float = 0.0
    total_pips: float = 0.0
    total_pnl_value: float = 0.0
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
        win_increment: float,
        *,
        timestamp: Any,
        pnl_value: Optional[float] = None,
    ) -> None:
        pnl_val = float(pnl_pips)
        pnl_equity = float(pnl_value) if pnl_value is not None else pnl_val
        self.trades += 1
        self.total_pips += pnl_val
        self.total_pnl_value += pnl_equity
        try:
            win_value = float(win_increment)
        except (TypeError, ValueError):
            win_value = 0.0
        self.wins += win_value
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
            "total_pnl_value": self.total_pnl_value,
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
    rv_band_min_or_atr_ratio: Dict[str, float] = field(default_factory=dict)
    rv_band_cuts: List[float] = field(default_factory=lambda: [0.005, 0.015])  # tuned for 5m FX RV scale
    spread_bands: Dict[str, float] = field(default_factory=lambda: {"narrow": 0.5, "normal": 1.2, "wide": 99})
    # Spread input/threshold configuration
    spread_input_mode: str = "price"
    spread_scale: Optional[float] = None
    allow_low_rv: bool = False
    allowed_sessions: Tuple[str, ...] = ("LDN", "NY")
    allowed_timeframes: Optional[Tuple[str, ...]] = None
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

    def spread_to_pips(self, spread_value: Any, pip_size_value: float) -> float:
        """Convert an input spread reading to pip units.

        Parameters
        ----------
        spread_value:
            Raw spread value from market data. It may already be denominated in
            pips or expressed in price units.
        pip_size_value:
            Instrument pip size used when converting price differences to pips.

        Returns
        -------
        float
            Spread value expressed in pips. Non-numeric inputs fall back to
            ``0.0`` and invalid configuration values are ignored so the default
            behaviour (price→pip conversion) still applies.
        """

        try:
            spread_numeric = float(spread_value)
        except (TypeError, ValueError):
            return 0.0

        mode_raw = getattr(self, "spread_input_mode", "price")
        mode = str(mode_raw).strip().lower()

        if mode in {"pip", "pips"}:
            spread_pips = spread_numeric
        elif mode in {"pipette", "pipettes"}:
            spread_pips = spread_numeric * 0.1
        else:
            if pip_size_value <= 0.0:
                return spread_numeric
            spread_pips = spread_numeric / pip_size_value

        scale_raw = getattr(self, "spread_scale", None)
        try:
            scale_value: Optional[float] = (
                float(scale_raw) if scale_raw is not None else None
            )
        except (TypeError, ValueError):
            scale_value = None

        if scale_value is not None and scale_value > 0.0:
            spread_pips *= scale_value

        return spread_pips


class BacktestRunner:
    DEBUG_COUNT_KEYS: Tuple[str, ...] = (
        "no_breakout",
        "gate_block",
        "ev_reject",
        "ev_bypass",
        "zero_qty",
        "strategy_gate_error",
        "ev_threshold_error",
        "session_parse_error",
    )
    DEBUG_RECORD_FIELDS: Dict[str, Tuple[str, ...]] = {
        "no_breakout": ("ts",),
        "strategy_gate": (
            "ts",
            "side",
            "reason_stage",
            "or_atr_ratio",
            "min_or_atr_ratio",
            "rv_band",
            "allow_low_rv",
            "cooldown_bars",
            "bars_since",
            "signals_today",
            "max_signals_per_day",
            "loss_streak",
            "max_loss_streak",
            "daily_loss_pips",
            "max_daily_loss_pips",
            "daily_trade_count",
            "max_daily_trade_count",
            "atr_pips",
            "min_atr_pips",
            "max_atr_pips",
            "micro_trend",
            "min_micro_trend",
            "qty",
            "p_lcb",
            "sl_pips",
        ),
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
        "session_parse_error": ("ts", "text"),
        "trade": (
            "ts",
            "side",
            "tp_pips",
            "sl_pips",
            "cost_pips",
            "slip_est",
            "slip_real",
            "exit",
            "pnl_pips",
            "pnl_value",
        ),
        "trade_exit": (
            "ts",
            "side",
            "cost_pips",
            "slip_est",
            "slip_real",
            "exit",
            "pnl_pips",
            "pnl_value",
        ),
    }
    DAILY_COUNT_FIELDS: ClassVar[Tuple[str, ...]] = (
        "breakouts",
        "gate_pass",
        "gate_block",
        "ev_pass",
        "ev_reject",
        "fills",
    )
    DAILY_FLOAT_FIELDS: ClassVar[Tuple[str, ...]] = (
        "wins",
        "pnl_pips",
        "pnl_value",
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
        self.lifecycle = RunnerLifecycleManager(self)
        self.execution = RunnerExecutionManager(self)
        self.lifecycle.init_ev_state()
        cons_policy = self.rcfg.resolve_same_bar_policy("conservative")
        bridge_policy = self.rcfg.resolve_same_bar_policy("bridge")
        self.fill_engine_c = ConservativeFill(cons_policy)
        self.fill_engine_b = BridgeFill(
            same_bar_policy=bridge_policy,
            lam=float(self.rcfg.fill_bridge_lambda),
            drift_scale=float(self.rcfg.fill_bridge_drift_scale),
        )
        self.lifecycle.reset_runtime_state()
        self._ev_profile_lookup: Dict[tuple, Dict[str, Any]] = {}
        # Slip/size expectation tracking
        self.lifecycle.reset_slip_learning()

        # strategy
        self._strategy_cfg: Dict[str, Any] = deepcopy(self.rcfg.strategy.as_dict())
        self._instruments: List[str] = [self.symbol]
        self._initialise_strategy_instance()
        self._apply_ev_profile()

    def _init_ev_state(self) -> None:
        self.lifecycle.init_ev_state()

    def _reset_slip_learning(self) -> None:
        self.lifecycle.reset_slip_learning()

    def _reset_runtime_state(self) -> None:
        self.lifecycle.reset_runtime_state()

    def _initialise_strategy_instance(self) -> None:
        cfg_payload = deepcopy(self._strategy_cfg)
        instruments = list(self._instruments)
        self.stg = self.strategy_cls()
        self.stg.on_start(cfg_payload, instruments, {})
        self._strategy_gate_hook = self._resolve_strategy_hook("strategy_gate")
        self._ev_threshold_hook = self._resolve_strategy_hook("ev_threshold")

    def _build_rv_window(self) -> deque:
        return deque(maxlen=self.rcfg.rv_q_lookback_bars)

    def _create_metrics(self) -> Metrics:
        return Metrics(starting_equity=self._equity_live)

    def _hash_payload(self, payload: str) -> str:
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

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
        resume_skipped = getattr(self.lifecycle, "resume_skipped_bars", 0)
        if resume_skipped:
            runtime["resume_skipped_bars"] = int(resume_skipped)
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

    def _update_entry_context_from_mapping(
        self, ctx: EntryContext, data: Mapping[str, Any]
    ) -> None:
        alias_map = {"ev_oco": "ev_manager"}
        field_names = EntryContext.__dataclass_fields__.keys()
        for key, value in data.items():
            attr = alias_map.get(key, key)
            if attr not in field_names:
                continue
            if attr == "allowed_sessions":
                if value is None:
                    ctx.allowed_sessions = None
                elif isinstance(value, tuple):
                    ctx.allowed_sessions = value
                elif isinstance(value, (list, set)):
                    ctx.allowed_sessions = tuple(value)
                else:
                    ctx.allowed_sessions = (str(value),)
                continue
            if attr == "sizing_cfg" and isinstance(value, Mapping):
                setattr(ctx, attr, dict(value))
                continue
            if attr == "ev_key":
                if isinstance(value, tuple):
                    ctx.ev_key = value  # type: ignore[assignment]
                elif isinstance(value, (list, set)):
                    ctx.ev_key = tuple(value)  # type: ignore[assignment]
                continue
            setattr(ctx, attr, value)

    def _call_strategy_gate(
        self,
        ctx: EntryContext,
        pending: Any,
        *,
        ts: Optional[str],
        side: Optional[str],
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        if self._strategy_gate_hook is None:
            return True, None
        ctx_payload = ctx.to_mapping()
        try:
            allowed = bool(self._strategy_gate_hook(ctx_payload, pending))
        except Exception as exc:  # pragma: no cover - defensive diagnostics
            self.debug_counts["strategy_gate_error"] += 1
            self._append_debug_record(
                "strategy_gate_error",
                ts=ts,
                side=side,
                error=str(exc),
            )
            return True, None
        self._update_entry_context_from_mapping(ctx, ctx_payload)
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
        ctx: EntryContext,
        pending: Any,
        base_threshold: float,
        *,
        ts: Optional[str],
        side: Optional[str],
    ) -> float:
        if self._ev_threshold_hook is None:
            return base_threshold
        ctx_payload = ctx.to_mapping()
        try:
            threshold = float(self._ev_threshold_hook(ctx_payload, pending, base_threshold))
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
        self._update_entry_context_from_mapping(ctx, ctx_payload)
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
        pnl_value: float,
        qty: float,
        ctx_snapshot: Union[Mapping[str, Any], TradeContextSnapshot, None] = None,
    ) -> None:
        self.execution.log_trade_record(
            exit_ts=exit_ts,
            entry_ts=entry_ts,
            side=side,
            tp_pips=tp_pips,
            sl_pips=sl_pips,
            cost_pips=cost_pips,
            slip_est=slip_est,
            slip_real=slip_real,
            exit_reason=exit_reason,
            pnl_pips=pnl_pips,
            pnl_value=pnl_value,
            qty=qty,
            ctx_snapshot=ctx_snapshot,
        )

    def _finalize_trade(
        self,
        *,
        exit_ts: Any,
        entry_ts: Any,
        side: str,
        entry_px: float,
        exit_px: float,
        exit_reason: Optional[str],
        ctx_snapshot: Union[Mapping[str, Any], TradeContextSnapshot],
        ctx: Mapping[str, Any],
        qty_sample: float,
        slip_actual: float,
        ev_key: Optional[tuple],
        tp_pips: float,
        sl_pips: float,
        debug_stage: str,
        debug_extra: Optional[Mapping[str, Any]] = None,
        p_tp: Optional[float] = None,
    ) -> None:
        self.execution.finalize_trade(
            exit_ts=exit_ts,
            entry_ts=entry_ts,
            side=side,
            entry_px=entry_px,
            exit_px=exit_px,
            exit_reason=exit_reason,
            ctx_snapshot=ctx_snapshot,
            ctx=ctx,
            qty_sample=qty_sample,
            slip_actual=slip_actual,
            ev_key=ev_key,
            tp_pips=tp_pips,
            sl_pips=sl_pips,
            debug_stage=debug_stage,
            debug_extra=debug_extra,
            p_tp=p_tp,
        )

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
                self._daily_loss_pips = 0.0
                self._daily_trade_count = 0
                self._daily_pnl_pips = 0.0
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
        pipeline = FeaturePipeline(
            rcfg=self.rcfg,
            window=self.window,
            session_bars=self.session_bars,
            rv_hist=self.rv_hist,
            ctx_builder=self._build_ctx,
            context_consumer=self.stg.update_context,
        )
        features, _ = pipeline.compute(
            bar,
            session=session,
            new_session=new_session,
            calibrating=calibrating,
        )
        return features

    def _compute_exit_decision(
        self,
        *,
        pos: PositionState,
        bar: Mapping[str, Any],
        mode: str,
        pip_size_value: float,
        new_session: bool,
    ) -> ExitDecision:
        return self.execution.compute_exit_decision(
            pos=pos,
            bar=bar,
            mode=mode,
            pip_size_value=pip_size_value,
            new_session=new_session,
        )

    def _handle_active_position(
        self,
        *,
        bar: Dict[str, Any],
        ctx: Mapping[str, Any],
        mode: str,
        pip_size_value: float,
        new_session: bool,
    ) -> bool:
        return self.execution.handle_active_position(
            bar=bar,
            ctx=ctx,
            mode=mode,
            pip_size_value=pip_size_value,
            new_session=new_session,
        )

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
        self.execution.resolve_calibration_positions(
            bar=bar,
            ctx=ctx,
            new_session=new_session,
            calibrating=calibrating,
            mode=mode,
            pip_size_value=pip_size_value,
        )

    def _evaluate_entry_conditions(
        self,
        *,
        pending: Any,
        features: FeatureBundle,
    ) -> EntryEvaluation:
        return EntryGate(self).evaluate(pending=pending, features=features)

    def _evaluate_ev_threshold(
        self,
        *,
        entry: EntryEvaluation,
        pending: Any,
        calibrating: bool,
        timestamp: Optional[str],
    ) -> EVEvaluation:
        return EVGate(self).evaluate(
            entry=entry,
            pending=pending,
            calibrating=calibrating,
            timestamp=timestamp,
        )

    def _check_slip_and_sizing(
        self,
        *,
        ctx: EVContext,
        ev_result: EVEvaluation,
        calibrating: bool,
        timestamp: Optional[str],
    ) -> SizingEvaluation:
        return SizingGate(self).evaluate(
            ctx=ctx,
            ev_result=ev_result,
            calibrating=calibrating,
            timestamp=timestamp,
        )

    def _compose_trade_context_snapshot(
        self,
        *,
        ctx: Union[EntryContext, EVContext, SizingContext],
        features: FeatureBundle,
    ) -> TradeContextSnapshot:
        return build_trade_context_snapshot(
            ctx=ctx,
            bar_input=features.bar_input,
        )



    def _maybe_enter_trade(
        self,
        *,
        bar: Dict[str, Any],
        features: FeatureBundle,
        mode: str,
        pip_size_value: float,
        calibrating: bool,
    ) -> None:
        self.execution.maybe_enter_trade(
            bar=bar,
            features=features,
            mode=mode,
            pip_size_value=pip_size_value,
            calibrating=calibrating,
        )



    def _process_fill_result(
        self,
        *,
        intent: Any,
        spec: OrderSpec,
        result: Mapping[str, Any],
        bar: Mapping[str, Any],
        ctx: Mapping[str, Any],
        ctx_dbg: Union[EntryContext, EVContext, SizingContext],
        trade_ctx_snapshot: TradeContextSnapshot,
        calibrating: bool,
        pip_size_value: float,
    ) -> Optional[PositionState]:
        return self.execution.process_fill_result(
            intent=intent,
            spec=spec,
            result=result,
            bar=bar,
            ctx=ctx,
            ctx_dbg=ctx_dbg,
            trade_ctx_snapshot=trade_ctx_snapshot,
            calibrating=calibrating,
            pip_size_value=pip_size_value,
        )

    def _record_trade_metrics(
        self,
        pnl_pips: float,
        win_increment: float,
        *,
        timestamp: Any,
        pnl_value: Optional[float] = None,
    ) -> None:
        self.execution.record_trade_metrics(
            pnl_pips,
            win_increment,
            timestamp=timestamp,
            pnl_value=pnl_value,
        )

    # ---------- State persistence ----------
    def _config_fingerprint(self) -> str:
        return self.lifecycle.config_fingerprint()

    def export_state(self) -> Dict[str, Any]:
        return self.lifecycle.export_state()

    def _apply_state_dict(self, state: Mapping[str, Any]) -> bool:
        return self.lifecycle.apply_state_dict(state)

    def load_state(self, state: Dict[str, Any]) -> bool:
        return self.lifecycle.load_state(state)

    def _restore_loaded_state_snapshot(self) -> None:
        self.lifecycle.restore_loaded_state_snapshot()

    def load_state_file(self, path: str) -> bool:
        return self.lifecycle.load_state_file(path)

    def _band_spread(self, spread_pips: float) -> str:
        bands = self.rcfg.spread_bands
        eps = 1e-9
        if spread_pips <= bands["narrow"] + eps:
            return "narrow"
        if spread_pips <= bands["normal"] + eps:
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
    ) -> EntryContext:
        ps = pip_size(self.symbol)
        spread_raw = bar.get("spread", 0.0)
        spread_pips = self.rcfg.spread_to_pips(spread_raw, ps)
        if spread_pips < 0.0:
            spread_pips = 0.0

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

        ev_mode_value = str(self.rcfg.ev_mode).lower()
        threshold_ctx = self.rcfg.threshold_lcb_pip
        if ev_mode_value == "off":
            threshold_ctx = float("-inf")

        spread_band = self._band_spread(spread_pips)
        rv_band = self._band_rv(realized_vol_value, session)
        min_or_value = self.rcfg.min_or_atr_ratio
        rv_band_floor = getattr(self.rcfg, "rv_band_min_or_atr_ratio", None)
        if isinstance(rv_band_floor, Mapping):
            overrides: Dict[str, float] = {}
            for key, raw_value in rv_band_floor.items():
                if key is None:
                    continue
                try:
                    numeric = float(raw_value)
                except (TypeError, ValueError):
                    continue
                if not math.isfinite(numeric):
                    continue
                overrides[str(key).strip().lower()] = numeric
            key_lower = str(rv_band).strip().lower()
            override = overrides.get(key_lower)
            if override is not None:
                min_or_value = override
        allowed_sessions: Optional[Tuple[str, ...]] = None
        if self.rcfg.allowed_sessions:
            allowed_sessions = tuple(self.rcfg.allowed_sessions)
        key = self._ev_key(session, spread_band, rv_band)
        ev_manager = self._get_ev_manager(key)
        ev_profile_stats = self._ev_profile_lookup.get(key)
        fallback_win_rate: Optional[float] = None
        extra_params = getattr(self.rcfg.strategy, "extra_params", {})
        if isinstance(extra_params, Mapping):
            fallback_raw = extra_params.get("fallback_win_rate")
            try:
                if fallback_raw is not None:
                    fallback_win_rate = float(fallback_raw)
            except (TypeError, ValueError):
                fallback_win_rate = None
        # Expected slip cost derived from learnt coefficients (per spread band)
        expected_slip = 0.0
        if getattr(self.rcfg, "include_expected_slip", False):
            coeff = float(
                self.slip_a.get(
                    spread_band, self.rcfg.slip_curve.get(spread_band, {}).get("a", 0.0)
                )
            )
            intercept = float(self.rcfg.slip_curve.get(spread_band, {}).get("b", 0.0))
            qty_est = self.qty_ewma.get(spread_band, 0.0)
            if qty_est <= 0.0:
                qty_est = 1.0
            expected_slip = max(0.0, coeff * qty_est + intercept)
        cost_pips = spread_pips + expected_slip
        return EntryContext(
            session=session,
            spread_band=spread_band,
            rv_band=rv_band,
            slip_cap_pip=self.rcfg.slip_cap_pip,
            threshold_lcb_pip=threshold_ctx,
            or_atr_ratio=or_ratio,
            min_or_atr_ratio=min_or_value,
            allow_low_rv=self.rcfg.allow_low_rv,
            warmup_left=self._warmup_left,
            warmup_mult=0.05,
            cooldown_bars=self.rcfg.cooldown_bars,
            ev_mode=ev_mode_value,
            size_floor_mult=self.rcfg.size_floor_mult,
            base_cost_pips=spread_pips,
            expected_slip_pip=expected_slip,
            cost_pips=cost_pips,
            equity=self._equity_live,
            pip_value=pip_value_ctx,
            sizing_cfg=self.rcfg.build_sizing_cfg(),
            ev_key=key,
            ev_manager=ev_manager,
            ev_profile_stats=ev_profile_stats,
            fallback_win_rate=fallback_win_rate,
            allowed_sessions=allowed_sessions,
            loss_streak=self._loss_streak,
            daily_loss_pips=self._daily_loss_pips,
            daily_trade_count=self._daily_trade_count,
            daily_pnl_pips=self._daily_pnl_pips,
        )

    def _parse_session_timestamp(self, ts: str) -> Optional[datetime]:
        """Parse a timestamp string into a timezone-aware ``datetime``."""
        if not isinstance(ts, str):
            return None
        text = ts.strip()
        if not text:
            return None

        candidates: List[str] = []
        if text.endswith("Z"):
            candidates.append(f"{text[:-1]}+00:00")
        candidates.append(text)

        parsed: Optional[datetime] = None
        for candidate in candidates:
            if "-" not in candidate and ":" not in candidate:
                continue
            try:
                parsed = datetime.fromisoformat(candidate)
            except ValueError:
                continue
            else:
                break

        if parsed is not None:
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed

        def _collapse_offset(value: str) -> str:
            if len(value) >= 6 and value[-3] == ":" and value[-6] in ("+", "-"):
                return value[:-3] + value[-2:]
            return value

        fallback_candidates: List[str] = [text]
        if text.endswith("Z"):
            fallback_candidates.append(f"{text[:-1]}+0000")

        extended_candidates = list(fallback_candidates)
        for candidate in extended_candidates:
            collapsed = _collapse_offset(candidate)
            if collapsed != candidate:
                fallback_candidates.append(collapsed)

        patterns: Tuple[str, ...] = (
            "%Y%m%dT%H%M%S.%f%z",
            "%Y%m%dT%H%M%S%z",
            "%Y%m%dT%H%M%S.%fZ",
            "%Y%m%dT%H%M%SZ",
            "%Y%m%dT%H%M%S.%f",
            "%Y%m%dT%H%M%S",
        )

        for candidate in fallback_candidates:
            for pattern in patterns:
                try:
                    parsed = datetime.strptime(candidate, pattern)
                except ValueError:
                    continue
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed
        return None

    def _session_of_ts(self, ts: str) -> str:
        """Very simple UTC-based session mapping.
        - TOK: 00:00–07:59 (inclusive of first hour), outside LDN/NY
        - LDN: 08:00–12:59
        - NY : 13:00–21:59
        else: TOK
        """
        parsed = self._parse_session_timestamp(ts)
        if parsed is None:
            self.debug_counts["session_parse_error"] += 1
            if self.debug:
                self._append_debug_record("session_parse_error", text=str(ts))
            return "TOK"
        hour = parsed.astimezone(timezone.utc).hour
        if 8 <= hour <= 12:
            return "LDN"
        if 13 <= hour <= 21:
            return "NY"
        return "TOK"

    def _resolve_allowed_timeframes(
        self, override: Optional[Iterable[Any]] = None
    ) -> Tuple[str, ...]:
        if override is not None:
            return _normalise_timeframes(override)
        config_timeframes = getattr(self.rcfg, "allowed_timeframes", None)
        return _normalise_timeframes(config_timeframes)

    def run_partial(
        self,
        bars: List[Dict[str, Any]],
        mode: str = "conservative",
        allowed_timeframes: Optional[Iterable[Any]] = None,
    ) -> Metrics:
        ps = pip_size(self.symbol)
        allowed_tf = self._resolve_allowed_timeframes(allowed_timeframes)
        for bar in bars:
            if self.lifecycle.should_skip_bar(bar):
                continue
            if not validate_bar(bar, allowed_timeframes=allowed_tf):
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

        Each invocation reinstantiates the strategy so per-strategy caches and
        pending signals are cleared before processing the provided bars.
        """
        self._initialise_strategy_instance()
        self._reset_runtime_state()
        self._init_ev_state()
        self._reset_slip_learning()
        self._ev_profile_lookup = {}
        self._apply_ev_profile()
        self._restore_loaded_state_snapshot()
        allowed_tf = self._resolve_allowed_timeframes()
        return self.run_partial(bars, mode=mode, allowed_timeframes=allowed_tf)
