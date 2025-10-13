from __future__ import annotations
import copy
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, TYPE_CHECKING

from core.ev_gate import BetaBinomialEV, TLowerEV
from core.runner_state import (
    ActivePositionState,
    CalibrationPositionState,
    deserialize_position_state,
    serialize_position_state,
)

if TYPE_CHECKING:
    from core.runner import BacktestRunner


class RunnerLifecycleManager:
    """Encapsulates runtime state and persistence flows for ``BacktestRunner``."""

    def __init__(self, runner: "BacktestRunner") -> None:
        self._runner = runner
        self._loaded_state_snapshot: Optional[Dict[str, Any]] = None
        self._restore_loaded_state: bool = False
        self._resume_cutoff_dt: Optional[datetime] = None
        self._resume_skipped_bars: int = 0

    # ----- Initialisation helpers -------------------------------------------------
    def init_ev_state(self) -> None:
        runner = self._runner
        runner.ev_global = BetaBinomialEV(
            conf_level=0.95,
            decay=runner.rcfg.ev_decay,
            prior_alpha=runner.rcfg.prior_alpha,
            prior_beta=runner.rcfg.prior_beta,
        )
        runner.ev_buckets = {}
        runner.ev_var = TLowerEV(conf_level=0.95, decay=runner.rcfg.ev_decay)

    def reset_slip_learning(self) -> None:
        runner = self._runner
        runner.slip_a = {
            "narrow": runner.rcfg.slip_curve.get("narrow", {}).get("a", 0.0),
            "normal": runner.rcfg.slip_curve.get("normal", {}).get("a", 0.0),
            "wide": runner.rcfg.slip_curve.get("wide", {}).get("a", 0.0),
        }
        runner.qty_ewma = {"narrow": 0.0, "normal": 0.0, "wide": 0.0}

    def reset_runtime_state(self) -> None:
        runner = self._runner
        runner._equity_live = float(runner.equity)
        runner.metrics = runner._create_metrics()
        runner.records = []
        runner.window = []
        runner.session_bars = []
        runner.debug_counts = {key: 0 for key in runner.DEBUG_COUNT_KEYS}
        runner.debug_records = []
        runner.daily = {}
        runner._current_daily_entry = None
        runner.rv_hist = {
            "TOK": runner._build_rv_window(),
            "LDN": runner._build_rv_window(),
            "NY": runner._build_rv_window(),
        }
        runner.rv_thresh = {"TOK": None, "LDN": None, "NY": None}
        runner.calib_positions = []
        runner.pos = None
        runner._warmup_left = max(0, int(runner.rcfg.warmup_trades))
        runner._last_session = None
        runner._last_day = None
        runner._current_date = None
        runner._day_count = 0
        runner._last_timestamp = None
        self._resume_cutoff_dt = None
        self._resume_skipped_bars = 0

    # ----- Persistence ------------------------------------------------------------
    def config_fingerprint(self) -> str:
        runner = self._runner
        cfg = {
            "symbol": runner.symbol,
            "threshold_lcb_pip": runner.rcfg.threshold_lcb_pip,
            "min_or_atr_ratio": runner.rcfg.min_or_atr_ratio,
            "rv_band_cuts": runner.rcfg.rv_band_cuts,
            "or_n": runner.rcfg.or_n,
            "decay": runner.ev_global.decay,
            "conf": runner.ev_global.conf_level,
        }
        payload = json.dumps(cfg, sort_keys=True)
        return runner._hash_payload(payload)

    def _parse_resume_timestamp(self, value: Any) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            dt_value = value
        else:
            try:
                text = str(value).strip()
            except Exception:
                return None
            if not text:
                return None
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            try:
                dt_value = datetime.fromisoformat(text)
            except ValueError:
                return None
        if dt_value.tzinfo is None:
            dt_value = dt_value.replace(tzinfo=timezone.utc)
        else:
            dt_value = dt_value.astimezone(timezone.utc)
        return dt_value

    def _restore_metrics_snapshot(self, payload: Mapping[str, Any]) -> None:
        runner = self._runner
        metrics = runner.metrics

        try:
            metrics.trades = int(payload.get("trades", metrics.trades))
        except Exception:
            pass
        try:
            metrics.wins = float(payload.get("wins", metrics.wins))
        except Exception:
            pass
        try:
            metrics.total_pips = float(payload.get("total_pips", metrics.total_pips))
        except Exception:
            pass
        try:
            metrics.total_pnl_value = float(
                payload.get("total_pnl_value", metrics.total_pnl_value)
            )
        except Exception:
            pass

        trade_returns = []
        for value in payload.get("trade_returns", []) or []:
            try:
                trade_returns.append(float(value))
            except (TypeError, ValueError):
                continue
        if trade_returns:
            metrics.trade_returns = trade_returns
        else:
            metrics.trade_returns = []

        equity_curve: List[tuple[str, float]] = []
        for entry in payload.get("equity_curve", []) or []:
            if not isinstance(entry, (list, tuple)) or len(entry) != 2:
                continue
            ts_value = str(entry[0])
            try:
                equity_value = float(entry[1])
            except (TypeError, ValueError):
                continue
            equity_curve.append((ts_value, equity_value))
        metrics.equity_curve = equity_curve

        equity_seed = payload.get("equity_seed")
        if isinstance(equity_seed, (list, tuple)) and len(equity_seed) == 2:
            seed_ts = str(equity_seed[0])
            try:
                seed_equity = float(equity_seed[1])
            except (TypeError, ValueError):
                seed_equity = metrics.starting_equity
            metrics._equity_seed = (seed_ts, seed_equity)
        elif equity_seed is None:
            metrics._equity_seed = None

        runtime_payload = payload.get("runtime")
        if isinstance(runtime_payload, Mapping):
            metrics.runtime = dict(runtime_payload)
            resume_count = runtime_payload.get("resume_skipped_bars")
            try:
                self._resume_skipped_bars = int(resume_count)
            except (TypeError, ValueError):
                self._resume_skipped_bars = 0

        daily_payload = payload.get("daily")
        restored_daily: Dict[str, Dict[str, Any]] = {}
        if isinstance(daily_payload, Mapping):
            for day, values in daily_payload.items():
                try:
                    day_key = str(day)
                except Exception:
                    continue
                if not isinstance(values, Mapping):
                    continue
                restored_daily[day_key] = dict(values)
        runner.daily = restored_daily
        if runner.daily:
            last_day = sorted(runner.daily.keys())[-1]
            runner._current_daily_entry = runner.daily.get(last_day)
        else:
            runner._current_daily_entry = None
        if runner.daily:
            metrics.daily = {day: dict(values) for day, values in runner.daily.items()}
        else:
            metrics.daily = {}

    def export_state(self) -> Dict[str, Any]:
        runner = self._runner
        buckets: Dict[str, Dict[str, float]] = {}
        for k, ev in runner.ev_buckets.items():
            key = f"{k[0]}:{k[1]}:{k[2]}"
            buckets[key] = {"alpha": ev.alpha, "beta": ev.beta}
        slip_a = getattr(runner, "slip_a", None)
        if isinstance(slip_a, Mapping):
            slip_a_payload: Any = dict(slip_a)
        else:
            slip_a_payload = slip_a

        qty_ewma = getattr(runner, "qty_ewma", None)
        if isinstance(qty_ewma, Mapping):
            qty_ewma_payload: Any = dict(qty_ewma)
        else:
            qty_ewma_payload = qty_ewma

        state = {
            "meta": {
                "symbol": runner.symbol,
                "config_fingerprint": self.config_fingerprint(),
                "last_timestamp": runner._last_timestamp,
            },
            "ev_global": {
                "alpha": runner.ev_global.alpha,
                "beta": runner.ev_global.beta,
                "prior_alpha": runner.ev_global.prior_alpha,
                "prior_beta": runner.ev_global.prior_beta,
                "decay": runner.ev_global.decay,
                "conf": runner.ev_global.conf_level,
            },
            "ev_buckets": buckets,
            "slip": {
                "a": slip_a_payload,
                "curve": runner.rcfg.slip_curve,
                "ewma_alpha": getattr(runner.rcfg, "slip_ewma_alpha", 0.1),
                "ewma": qty_ewma_payload,
            },
            "rv_thresh": runner.rv_thresh,
            "runtime": {
                "warmup_left": runner._warmup_left,
                "day_count": runner._day_count,
                "current_date": runner._current_date,
                "last_session": runner._last_session,
                "_equity_live": runner._equity_live,
            },
        }
        metrics_state: Dict[str, Any] = {
            "trades": runner.metrics.trades,
            "wins": runner.metrics.wins,
            "total_pips": runner.metrics.total_pips,
            "total_pnl_value": runner.metrics.total_pnl_value,
            "trade_returns": list(runner.metrics.trade_returns),
            "equity_curve": [
                [ts, equity] for ts, equity in list(runner.metrics.equity_curve)
            ],
        }
        if runner.metrics._equity_seed is not None:
            metrics_state["equity_seed"] = list(runner.metrics._equity_seed)
        if runner.metrics.runtime:
            runtime_snapshot = dict(runner.metrics.runtime)
            if self._resume_skipped_bars:
                runtime_snapshot.setdefault(
                    "resume_skipped_bars", self._resume_skipped_bars
                )
            metrics_state["runtime"] = runtime_snapshot
        if runner.daily:
            metrics_state["daily"] = {
                day: dict(values) for day, values in runner.daily.items()
            }
        state["metrics"] = metrics_state
        if runner.pos is not None:
            state["position"] = serialize_position_state(runner.pos)
        if runner.calib_positions:
            state["calibration_positions"] = [
                serialize_position_state(pos_state)
                for pos_state in runner.calib_positions
            ]
        return state

    def apply_state_dict(self, state: Mapping[str, Any]) -> None:
        runner = self._runner
        try:
            meta = state.get("meta", {})
        except Exception:
            meta = {}

        skip_state = False
        self._resume_cutoff_dt = None
        try:
            fp_state = meta.get("config_fingerprint")
            fp_now = self.config_fingerprint()
            if fp_state and fp_state != fp_now:
                msg = (
                    "state config_fingerprint mismatch "
                    f"(state={fp_state}, current={fp_now})"
                )
                try:
                    runner.metrics.debug.setdefault("warnings", []).append(msg)
                except Exception:
                    pass
                skip_state = True
        except Exception:
            pass

        if skip_state:
            return

        try:
            runner._last_timestamp = meta.get("last_timestamp", runner._last_timestamp)
            self._resume_cutoff_dt = self._parse_resume_timestamp(meta.get("last_timestamp"))

            ev_global = state.get("ev_global", {})
            try:
                runner.ev_global.alpha = float(ev_global.get("alpha", runner.ev_global.alpha))
                runner.ev_global.beta = float(ev_global.get("beta", runner.ev_global.beta))
                runner.ev_global.prior_alpha = float(
                    ev_global.get("prior_alpha", runner.ev_global.prior_alpha)
                )
                runner.ev_global.prior_beta = float(
                    ev_global.get("prior_beta", runner.ev_global.prior_beta)
                )
                runner.ev_global.decay = float(
                    ev_global.get("decay", runner.ev_global.decay)
                )
                runner.ev_global.conf_level = float(
                    ev_global.get("conf", runner.ev_global.conf_level)
                )
            except Exception:
                pass

            runner.ev_buckets = {}
            ev_buckets = state.get("ev_buckets", {})
            for key_str, params in ev_buckets.items():
                try:
                    session, spread, rv = key_str.split(":")
                except ValueError:
                    continue
                ev = BetaBinomialEV(
                    conf_level=runner.ev_global.conf_level,
                    decay=runner.ev_global.decay,
                    prior_alpha=runner.ev_global.prior_alpha,
                    prior_beta=runner.ev_global.prior_beta,
                )
                try:
                    ev.alpha = float(params.get("alpha", ev.alpha))
                    ev.beta = float(params.get("beta", ev.beta))
                except Exception:
                    pass
                runner.ev_buckets[(session, spread, rv)] = ev

            slip = state.get("slip", {})
            slip_a = slip.get("a")
            if isinstance(slip_a, Mapping):
                base_slip_a = dict(getattr(runner, "slip_a", {}))
                for band, value in slip_a.items():
                    try:
                        base_slip_a[band] = float(value)
                    except (TypeError, ValueError):
                        continue
                runner.slip_a = base_slip_a
            qty_a = slip.get("ewma")
            if isinstance(qty_a, Mapping):
                base_qty = dict(getattr(runner, "qty_ewma", {}))
                for band, value in qty_a.items():
                    try:
                        base_qty[band] = float(value)
                    except (TypeError, ValueError):
                        continue
                runner.qty_ewma = base_qty

            rv_th = state.get("rv_thresh")
            if rv_th:
                runner.rv_thresh = rv_th

            runtime = state.get("runtime", {})
            if "_equity_live" in runtime:
                try:
                    runner._equity_live = float(runtime.get("_equity_live", runner._equity_live))
                    if getattr(runner, "metrics", None) is not None:
                        runner.metrics.starting_equity = runner._equity_live
                except Exception:
                    pass
            if "warmup_left" in runtime:
                try:
                    runner._warmup_left = max(
                        0, int(runtime.get("warmup_left", runner._warmup_left))
                    )
                except Exception:
                    pass
            if "day_count" in runtime:
                try:
                    runner._day_count = max(
                        0, int(runtime.get("day_count", runner._day_count))
                    )
                except Exception:
                    pass
            if runtime.get("current_date"):
                runner._current_date = runtime.get("current_date")
            if runtime.get("last_session"):
                runner._last_session = runtime.get("last_session")

            position_state = state.get("position")
            if position_state:
                try:
                    runner.pos = deserialize_position_state(
                        position_state, calibration=False
                    )
                except Exception:
                    runner.pos = None
            else:
                runner.pos = None

            calib_payload = state.get("calibration_positions", [])
            restored_calib: List[CalibrationPositionState] = []
            for raw in calib_payload:
                try:
                    restored_calib.append(
                        deserialize_position_state(raw, calibration=True)
                    )
                except Exception:
                    continue
            runner.calib_positions = restored_calib

            metrics_payload = state.get("metrics")
            if isinstance(metrics_payload, Mapping):
                self._restore_metrics_snapshot(metrics_payload)
        except Exception:
            pass

    def load_state(self, state: Dict[str, Any]) -> None:
        self.apply_state_dict(state)
        snapshot: Optional[Dict[str, Any]] = None
        try:
            snapshot = copy.deepcopy(state)
        except Exception:
            try:
                snapshot = json.loads(json.dumps(state))
            except Exception:
                snapshot = None
        self._loaded_state_snapshot = snapshot if snapshot is not None else None
        self._restore_loaded_state = self._loaded_state_snapshot is not None

    def restore_loaded_state_snapshot(self) -> None:
        if not self._restore_loaded_state:
            return
        if not self._loaded_state_snapshot:
            self._restore_loaded_state = False
            return
        self.apply_state_dict(self._loaded_state_snapshot)
        self._restore_loaded_state = False

    def load_state_file(self, path: str) -> None:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.load_state(data)
        except Exception:
            pass

    def should_skip_bar(self, bar: Mapping[str, Any]) -> bool:
        if self._resume_cutoff_dt is None:
            return False
        ts_value: Any
        try:
            ts_value = bar.get("timestamp")
        except Exception:
            ts_value = None
        dt_value = self._parse_resume_timestamp(ts_value)
        if dt_value is None:
            return False
        if dt_value <= self._resume_cutoff_dt:
            self._resume_skipped_bars += 1
            return True
        self._resume_cutoff_dt = None
        return False

    @property
    def resume_skipped_bars(self) -> int:
        return max(0, int(self._resume_skipped_bars))

