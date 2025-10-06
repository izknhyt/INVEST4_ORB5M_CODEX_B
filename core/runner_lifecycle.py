from __future__ import annotations
import copy
import json
from typing import Any, Dict, List, Mapping, Optional, TYPE_CHECKING

from core.ev_gate import BetaBinomialEV, TLowerEV
from core.runner_state import ActivePositionState, CalibrationPositionState

if TYPE_CHECKING:
    from core.runner import BacktestRunner


class RunnerLifecycleManager:
    """Encapsulates runtime state and persistence flows for ``BacktestRunner``."""

    def __init__(self, runner: "BacktestRunner") -> None:
        self._runner = runner
        self._loaded_state_snapshot: Optional[Dict[str, Any]] = None
        self._restore_loaded_state: bool = False

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

    def export_state(self) -> Dict[str, Any]:
        runner = self._runner
        buckets: Dict[str, Dict[str, float]] = {}
        for k, ev in runner.ev_buckets.items():
            key = f"{k[0]}:{k[1]}:{k[2]}"
            buckets[key] = {"alpha": ev.alpha, "beta": ev.beta}
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
                "a": getattr(runner, "slip_a", None),
                "curve": runner.rcfg.slip_curve,
                "ewma_alpha": getattr(runner.rcfg, "slip_ewma_alpha", 0.1),
            },
            "rv_thresh": runner.rv_thresh,
            "runtime": {
                "warmup_left": runner._warmup_left,
                "day_count": runner._day_count,
                "current_date": runner._current_date,
                "last_session": runner._last_session,
            },
        }
        if runner.pos is not None:
            state["position"] = runner.pos.as_dict()
        if runner.calib_positions:
            state["calibration_positions"] = [
                pos_state.as_dict() for pos_state in runner.calib_positions
            ]
        return state

    def apply_state_dict(self, state: Mapping[str, Any]) -> None:
        runner = self._runner
        try:
            meta = state.get("meta", {})
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
            except Exception:
                pass

            runner._last_timestamp = meta.get("last_timestamp", runner._last_timestamp)

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
                runner.slip_a = dict(slip_a)
            qty_a = slip.get("ewma")
            if isinstance(qty_a, Mapping):
                runner.qty_ewma = dict(qty_a)

            rv_th = state.get("rv_thresh")
            if rv_th:
                runner.rv_thresh = rv_th

            runtime = state.get("runtime", {})
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
                    runner.pos = ActivePositionState.from_dict(position_state)
                except Exception:
                    runner.pos = None
            else:
                runner.pos = None

            calib_payload = state.get("calibration_positions", [])
            restored_calib: List[CalibrationPositionState] = []
            for raw in calib_payload:
                try:
                    restored_calib.append(CalibrationPositionState.from_dict(raw))
                except Exception:
                    continue
            runner.calib_positions = restored_calib
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

