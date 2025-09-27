import types

from scripts.config_utils import build_runner_config
from core.runner import RunnerConfig


def make_args(**kwargs):
    namespace = types.SimpleNamespace()
    for k, v in kwargs.items():
        setattr(namespace, k, v)
    return namespace


def test_build_runner_config_applies_overrides():
    args = make_args(
        threshold_lcb=0.3,
        min_or_atr=0.4,
        rv_cuts="0.004,0.012",
        allow_low_rv=True,
        allowed_sessions="LDN,NY",
        warmup=10,
        prior_alpha=3,
        prior_beta=4,
        include_expected_slip=True,
        rv_quantile=True,
        calibrate_days=5,
        ev_mode="mean",
        size_floor=0.2,
        or_n=4,
        k_tp=1.2,
        k_sl=0.6,
        k_tr=0.1,
        cooldown_bars=7,
    )
    rcfg = build_runner_config(args)

    assert rcfg.threshold_lcb_pip == 0.3
    assert rcfg.min_or_atr_ratio == 0.4
    assert rcfg.rv_band_cuts == [0.004, 0.012]
    assert rcfg.allow_low_rv is True
    assert rcfg.allowed_sessions == ("LDN", "NY")
    assert rcfg.warmup_trades == 10
    assert rcfg.prior_alpha == 3
    assert rcfg.prior_beta == 4
    assert rcfg.include_expected_slip is True
    assert rcfg.rv_qcalib_enabled is True
    assert rcfg.calibrate_days == 5
    assert rcfg.ev_mode == "mean"
    assert rcfg.size_floor_mult == 0.2
    assert rcfg.or_n == 4
    assert rcfg.k_tp == 1.2
    assert rcfg.k_sl == 0.6
    assert rcfg.k_tr == 0.1
    assert rcfg.cooldown_bars == 7


def test_build_runner_config_does_not_mutate_base():
    base = RunnerConfig()
    base.threshold_lcb_pip = 0.7
    base.strategy.or_n = 9

    args = make_args(threshold_lcb=0.2, or_n=5)
    rcfg = build_runner_config(args, base)

    assert rcfg.threshold_lcb_pip == 0.2
    assert rcfg.or_n == 5
    assert base.threshold_lcb_pip == 0.7
    assert base.or_n == 9
