import math

from core.fill_engine import (
    BridgeFill,
    ConservativeFill,
    OrderSpec,
    SameBarPolicy,
)


def test_conservative_same_bar_default_sl_first():
    spec = OrderSpec(
        side="BUY",
        entry=100.0,
        tp_pips=5.0,
        sl_pips=5.0,
        trail_pips=0.0,
        slip_cap_pip=3.0,
    )
    bar = {"o": 99.95, "h": 100.20, "l": 99.40, "c": 99.80, "pip": 0.01, "spread": 0.001}
    result = ConservativeFill().simulate(bar, spec)
    assert result["fill"] is True
    assert result["exit_reason"] == "sl"
    assert math.isclose(result["exit_px"], 99.95, abs_tol=1e-9)


def test_conservative_same_bar_tp_first_policy():
    spec = OrderSpec(
        side="BUY",
        entry=100.0,
        tp_pips=5.0,
        sl_pips=5.0,
        trail_pips=0.0,
        slip_cap_pip=3.0,
        same_bar_policy=SameBarPolicy.TP_FIRST,
    )
    bar = {"o": 99.95, "h": 100.20, "l": 99.40, "c": 100.10, "pip": 0.01, "spread": 0.001}
    result = ConservativeFill().simulate(bar, spec)
    assert result["exit_reason"] == "tp"
    assert math.isclose(result["exit_px"], 100.05, abs_tol=1e-9)


def test_bridge_fill_returns_probability_in_same_bar():
    spec = OrderSpec(
        side="BUY",
        entry=150.0,
        tp_pips=8.0,
        sl_pips=12.0,
        trail_pips=0.0,
        slip_cap_pip=2.0,
        same_bar_policy=SameBarPolicy.PROBABILISTIC,
    )
    bar = {"o": 149.90, "h": 150.25, "l": 149.70, "c": 150.15, "pip": 0.01, "spread": 0.001}
    result = BridgeFill().simulate(bar, spec)
    assert result["exit_reason"] in {"tp", "sl"}
    assert 0.0 < result["p_tp"] < 1.0
    expected_mix = result["p_tp"] * (spec.entry + spec.tp_pips * bar["pip"]) + (1 - result["p_tp"]) * (
        spec.entry - spec.sl_pips * bar["pip"]
    )
    assert math.isclose(result["exit_px"], expected_mix, rel_tol=1e-9, abs_tol=1e-9)


def test_trailing_exit_within_same_bar():
    spec = OrderSpec(
        side="BUY",
        entry=132.42,
        tp_pips=20.0,
        sl_pips=15.0,
        trail_pips=10.0,
        slip_cap_pip=2.5,
    )
    bar = {"o": 132.40, "h": 132.78, "l": 132.30, "c": 132.55, "pip": 0.01, "spread": 0.001}
    result = ConservativeFill().simulate(bar, spec)
    assert result["exit_reason"] == "trail"
    assert math.isclose(result["exit_px"], 132.68, abs_tol=1e-9)


def test_trailing_stop_carry_returns_next_stop():
    spec = OrderSpec(
        side="BUY",
        entry=105.0,
        tp_pips=30.0,
        sl_pips=20.0,
        trail_pips=10.0,
        slip_cap_pip=2.0,
    )
    bar = {"o": 104.90, "h": 105.25, "l": 105.16, "c": 105.20, "pip": 0.01, "spread": 0.001}
    result = BridgeFill().simulate(bar, spec)
    assert result["exit"] is None
    assert "trail_stop_px" in result
    assert math.isclose(result["trail_stop_px"], 105.15, abs_tol=1e-9)
