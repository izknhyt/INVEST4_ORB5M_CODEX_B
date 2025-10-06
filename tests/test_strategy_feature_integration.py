import pytest
from unittest.mock import patch

from strategies.session_momentum_continuation import SessionMomentumContinuation
from strategies.tokyo_micro_mean_reversion import TokyoMicroMeanReversion


@pytest.fixture
def scalping_ctx() -> dict:
    return {
        "session": "TOK",
        "allowed_sessions": ["TOK"],
        "spread_band": "narrow",
        "rv_band": "mid",
        "equity": 75000.0,
        "pip_value": 10.0,
        "sizing_cfg": {
            "risk_per_trade_pct": 0.08,
            "kelly_fraction": 0.25,
            "units_cap": 3.0,
            "max_trade_loss_pct": 0.6,
        },
        "cooldown_bars": 0,
    }


@pytest.fixture
def day_ctx() -> dict:
    return {
        "session": "LDN",
        "allowed_sessions": ["LDN", "NY"],
        "spread_band": "normal",
        "rv_band": "mid",
        "equity": 150000.0,
        "pip_value": 9.5,
        "sizing_cfg": {
            "risk_per_trade_pct": 0.18,
            "kelly_fraction": 0.35,
            "units_cap": 4.0,
            "max_trade_loss_pct": 1.0,
        },
        "cooldown_bars": 0,
    }


def test_tokyo_micro_mean_reversion_emits_signal_with_micro_features(scalping_ctx: dict) -> None:
    strategy = TokyoMicroMeanReversion()
    strategy.on_start(
        {
            "zscore_threshold": 1.6,
            "trend_filter": 0.45,
            "atr_tp_mult": 0.5,
            "atr_sl_mult": 0.8,
            "default_tp_pips": 4.0,
            "default_sl_pips": 6.0,
        },
        ["USDJPY"],
        {},
    )
    bar = {
        "o": 112.610,
        "h": 112.645,
        "l": 112.598,
        "c": 112.632,
        "atr14": 0.42,
        "micro_zscore": 2.8,
        "micro_trend": 0.25,
        "mid_price": 112.6215,
        "trend_score": 0.1,
        "pullback": 0.12,
    }
    strategy.on_bar(bar)

    with patch("strategies.scalping_template.compute_qty_from_ctx", return_value=1.0):
        intents = list(strategy.signals(scalping_ctx))

    assert len(intents) == 1
    intent = intents[0]
    assert intent.side == "SELL"
    assert intent.oco is not None
    assert intent.oco["tp_pips"] > 0.0
    assert intent.oco["sl_pips"] > 0.0


def test_session_momentum_continuation_emits_signal_with_trend_features(day_ctx: dict) -> None:
    strategy = SessionMomentumContinuation()
    strategy.on_start(
        {
            "trend_threshold": 0.7,
            "pullback_threshold": 0.4,
            "min_adx": 18.0,
            "atr_tp_mult": 1.4,
            "atr_sl_mult": 1.9,
            "default_tp_pips": 16.0,
            "default_sl_pips": 24.0,
        },
        ["USDJPY"],
        {},
    )
    bar = {
        "o": 1.2035,
        "h": 1.2070,
        "l": 1.2010,
        "c": 1.2065,
        "atr14": 0.85,
        "trend_score": 0.82,
        "pullback": 0.18,
        "adx14": 24.0,
        "mid_price": 1.2040,
        "rv_band": "mid",
        "spread_band": "normal",
    }
    strategy.on_bar(bar)

    with patch("strategies.day_template.compute_qty_from_ctx", return_value=2.0):
        intents = list(strategy.signals(day_ctx))

    assert len(intents) == 1
    intent = intents[0]
    assert intent.side == "BUY"
    assert intent.oco is not None
    assert intent.oco["tp_pips"] > 0.0
    assert intent.oco["sl_pips"] > 0.0
