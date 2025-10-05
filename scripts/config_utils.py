from __future__ import annotations

import copy
from typing import Iterable, Optional

from core.runner import RunnerConfig


def _parse_allowed_sessions(value: Optional[str]) -> tuple[str, ...] | None:
    if value is None:
        return None
    cleaned = [s.strip().upper() for s in value.split(',') if s.strip()]
    return tuple(cleaned)


def build_runner_config(args, base: RunnerConfig | None = None) -> RunnerConfig:
    """Create a RunnerConfig from argparse Namespace shared across CLI entrypoints."""
    rcfg = copy.deepcopy(base) if base is not None else RunnerConfig()

    if getattr(args, "threshold_lcb", None) is not None:
        rcfg.threshold_lcb_pip = float(args.threshold_lcb)
    if getattr(args, "min_or_atr", None) is not None:
        rcfg.min_or_atr_ratio = float(args.min_or_atr)
    if getattr(args, "rv_cuts", None):
        try:
            c1, c2 = [float(x.strip()) for x in args.rv_cuts.split(',')]
            rcfg.rv_band_cuts = [c1, c2]
        except Exception:
            pass
    if getattr(args, "allow_low_rv", False):
        rcfg.allow_low_rv = True
    allowed_sessions = _parse_allowed_sessions(getattr(args, "allowed_sessions", None))
    if allowed_sessions is not None:
        rcfg.allowed_sessions = allowed_sessions

    if getattr(args, "warmup", None) is not None:
        rcfg.warmup_trades = int(args.warmup)
    if getattr(args, "prior_alpha", None) is not None:
        rcfg.prior_alpha = float(args.prior_alpha)
    if getattr(args, "prior_beta", None) is not None:
        rcfg.prior_beta = float(args.prior_beta)
    if getattr(args, "decay", None) is not None:
        rcfg.ev_decay = float(args.decay)
    if getattr(args, "include_expected_slip", False):
        rcfg.include_expected_slip = True
    if getattr(args, "rv_quantile", False):
        rcfg.rv_qcalib_enabled = True
    if getattr(args, "calibrate_days", None) is not None:
        rcfg.calibrate_days = int(args.calibrate_days)

    if getattr(args, "ev_mode", None) is not None:
        rcfg.ev_mode = args.ev_mode
    if getattr(args, "size_floor", None) is not None:
        rcfg.size_floor_mult = float(args.size_floor)

    if getattr(args, "fill_same_bar_policy", None) is not None:
        policy_value = str(args.fill_same_bar_policy)
        rcfg.fill_same_bar_policy_conservative = policy_value
        rcfg.fill_same_bar_policy_bridge = policy_value
    if getattr(args, "fill_same_bar_policy_conservative", None) is not None:
        rcfg.fill_same_bar_policy_conservative = str(args.fill_same_bar_policy_conservative)
    if getattr(args, "fill_same_bar_policy_bridge", None) is not None:
        rcfg.fill_same_bar_policy_bridge = str(args.fill_same_bar_policy_bridge)
    if getattr(args, "fill_bridge_lambda", None) is not None:
        rcfg.fill_bridge_lambda = float(args.fill_bridge_lambda)
    if getattr(args, "fill_bridge_drift_scale", None) is not None:
        rcfg.fill_bridge_drift_scale = float(args.fill_bridge_drift_scale)

    if getattr(args, "or_n", None) is not None:
        try:
            rcfg.or_n = int(args.or_n)
        except (ValueError, TypeError):
            pass
    if getattr(args, "k_tp", None) is not None:
        try:
            rcfg.k_tp = float(args.k_tp)
        except (ValueError, TypeError):
            pass
    if getattr(args, "k_sl", None) is not None:
        try:
            rcfg.k_sl = float(args.k_sl)
        except (ValueError, TypeError):
            pass
    if getattr(args, "k_tr", None) is not None:
        rcfg.k_tr = float(args.k_tr)
    if getattr(args, "cooldown_bars", None) is not None:
        rcfg.cooldown_bars = int(args.cooldown_bars)

    return rcfg
