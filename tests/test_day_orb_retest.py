import math

from strategies.day_orb_5m import DayORB5m


def _bar(h, l, c, window, atr=0.01, new_session=False):
    return {
        "h": h,
        "l": l,
        "c": c,
        "window": window,
        "atr14": atr,
        "new_session": new_session,
    }


def test_sell_breakout_waits_for_retest():
    strategy = DayORB5m()
    cfg = {
        "or_n": 2,
        "require_retest": True,
        "retest_max_bars": 6,
        "retest_tol_k": 0.0,
    }
    strategy.on_start(cfg, ["USDJPY"], {})

    or_seed_1 = {"h": 151.005, "l": 150.995}
    or_seed_2 = {"h": 151.004, "l": 150.996}

    # build opening range
    strategy.on_bar(_bar(151.005, 150.995, 151.000, [or_seed_1], new_session=True))
    strategy.on_bar(_bar(151.004, 150.996, 151.001, [or_seed_1, or_seed_2]))
    assert math.isclose(strategy.state["or_h"], 151.005)
    assert math.isclose(strategy.state["or_l"], 150.995)

    # Initial sell breakout
    sell_break = {"h": 150.997, "l": 150.990}
    strategy.on_bar(_bar(150.997, 150.990, 150.992, [or_seed_2, sell_break]))
    assert strategy.state["waiting_retest"]
    assert strategy.state["retest_direction"] == "sell"
    assert strategy.get_pending_signal() is None

    # Price keeps falling without retesting OR low. Previously the OR condition would
    # short-circuit and mark a retest; ensure it no longer does so.
    no_retest = {"h": 150.994, "l": 150.985}
    strategy.on_bar(_bar(150.994, 150.985, 150.988, [sell_break, no_retest]))
    assert strategy.state["waiting_retest"] is True
    assert strategy.state["retest_seen"] is False
    assert strategy.get_pending_signal() is None

    # Proper retest that tags the OR low from below
    retest = {"h": 150.996, "l": 150.988}
    strategy.on_bar(_bar(150.996, 150.988, 150.989, [no_retest, retest]))
    assert not strategy.state["waiting_retest"]
    assert strategy.state["retest_seen"] is True
    assert strategy.get_pending_signal() is None

    # Re-break to confirm entry
    confirm = {"h": 150.990, "l": 150.990 - 0.01}
    strategy.on_bar(_bar(confirm["h"], confirm["l"], 150.990 - 0.005, [retest, confirm]))
    pending = strategy.get_pending_signal()
    assert pending is not None
    assert pending["side"] == "SELL"


def _pending_signal():
    return {
        "side": "BUY",
        "tp_pips": 15.0,
        "sl_pips": 10.0,
        "trail_pips": 0.0,
        "entry": 151.25,
        "atr_pips": 15.0,
        "micro_trend": 0.0,
    }


def _base_ctx():
    return {
        "session": "LDN",
        "spread_band": "normal",
        "rv_band": "mid",
        "slip_cap_pip": 5.0,
        "threshold_lcb_pip": -10.0,
        "or_atr_ratio": 0.4,
        "min_or_atr_ratio": 0.25,
        "allow_low_rv": True,
        "warmup_left": 0,
        "warmup_mult": 0.05,
        "cooldown_bars": 0,
        "ev_mode": "off",
        "size_floor_mult": 0.05,
        "base_cost_pips": 0.2,
        "expected_slip_pip": 0.0,
        "cost_pips": 0.2,
        "equity": 100000.0,
        "pip_value": 10.0,
        "sizing_cfg": {
            "risk_per_trade_pct": 0.25,
            "kelly_fraction": 0.25,
            "units_cap": 5.0,
            "max_trade_loss_pct": 0.5,
        },
        "ev_key": ("LDN", "normal", "mid"),
        "ev_oco": None,
        "allowed_sessions": ["LDN"],
        "loss_streak": 0,
        "daily_loss_pips": 0.0,
        "daily_trade_count": 0,
        "daily_pnl_pips": 0.0,
    }


def _prep_strategy(cfg_overrides=None):
    strategy = DayORB5m()
    cfg = {
        "fallback_win_rate": 0.55,
        "max_loss_streak": 0,
        "max_daily_loss_pips": 0.0,
        "max_daily_trade_count": 0,
    }
    if cfg_overrides:
        cfg.update(cfg_overrides)
    strategy.on_start(cfg, ["USDJPY"], {})
    strategy.state["bar_idx"] = 100
    strategy.state["last_signal_bar"] = 10
    strategy._pending_signal = _pending_signal()
    return strategy


def test_loss_streak_guard_blocks_and_allows_after_reset():
    stg = _prep_strategy({"max_loss_streak": 2})
    ctx = _base_ctx()
    ctx["loss_streak"] = 2
    intents = list(stg.signals(ctx))
    assert intents == []
    assert stg._last_gate_reason == {
        "stage": "loss_streak_guard",
        "loss_streak": 2,
        "max_loss_streak": 2,
    }

    ctx["loss_streak"] = 1
    intents = list(stg.signals(ctx))
    assert intents, "Expected guard to lift once loss streak drops below threshold"


def test_daily_loss_guard_uses_cumulative_negative_pips():
    stg = _prep_strategy({"max_daily_loss_pips": 120.0})
    ctx = _base_ctx()
    ctx["daily_loss_pips"] = -150.0
    intents = list(stg.signals(ctx))
    assert intents == []
    assert stg._last_gate_reason == {
        "stage": "daily_loss_guard",
        "daily_loss_pips": -150.0,
        "max_daily_loss_pips": 120.0,
    }

    ctx["daily_loss_pips"] = -90.0
    intents = list(stg.signals(ctx))
    assert intents, "Daily loss under threshold should allow trading"


def test_daily_trade_cap_blocks_after_manifest_limit():
    stg = _prep_strategy({"max_daily_trade_count": 6})
    ctx = _base_ctx()
    ctx["daily_trade_count"] = 6
    intents = list(stg.signals(ctx))
    assert intents == []
    assert stg._last_gate_reason == {
        "stage": "daily_trade_guard",
        "daily_trade_count": 6,
        "max_daily_trade_count": 6,
    }

    ctx["daily_trade_count"] = 5
    intents = list(stg.signals(ctx))
    assert intents, "Trade count below cap should allow execution"


def test_daily_signal_cap_records_reason():
    stg = _prep_strategy({"max_signals_per_day": 4})
    stg.state["signals_today"] = 4
    ctx = _base_ctx()
    intents = list(stg.signals(ctx))
    assert intents == []
    assert stg._last_gate_reason == {
        "stage": "daily_signal_cap",
        "signals_today": 4,
        "max_signals_per_day": 4,
    }


def test_cooldown_guard_records_reason():
    stg = _prep_strategy({"cooldown_bars": 3})
    stg.state["last_signal_bar"] = stg.state["bar_idx"] - 1
    ctx = _base_ctx()
    ctx["cooldown_bars"] = 3
    intents = list(stg.signals(ctx))
    assert intents == []
    assert stg._last_gate_reason == {
        "stage": "cooldown_guard",
        "bars_since": 1,
        "cooldown_bars": 3,
    }


def test_atr_filter_records_min_and_max_rejections():
    stg = _prep_strategy({"min_atr_pips": 20.0})
    ctx = _base_ctx()
    stg._pending_signal["atr_pips"] = 15.0
    intents = list(stg.signals(ctx))
    assert intents == []
    assert stg._last_gate_reason == {
        "stage": "atr_filter",
        "atr_pips": 15.0,
        "min_atr_pips": 20.0,
    }

    stg = _prep_strategy({"max_atr_pips": 10.0})
    ctx = _base_ctx()
    stg._pending_signal["atr_pips"] = 15.0
    intents = list(stg.signals(ctx))
    assert intents == []
    assert stg._last_gate_reason == {
        "stage": "atr_filter",
        "atr_pips": 15.0,
        "max_atr_pips": 10.0,
    }


def test_micro_trend_filter_records_reason():
    stg = _prep_strategy({"min_micro_trend": 0.2})
    stg._pending_signal["micro_trend"] = 0.05
    ctx = _base_ctx()
    intents = list(stg.signals(ctx))
    assert intents == []
    assert stg._last_gate_reason == {
        "stage": "micro_trend_filter",
        "side": "BUY",
        "micro_trend": 0.05,
        "min_micro_trend": 0.2,
    }


def test_zero_qty_sets_sizing_guard_reason():
    stg = _prep_strategy()
    ctx = _base_ctx()
    ctx["equity"] = 0.0
    intents = list(stg.signals(ctx))
    assert intents == []
    assert stg._last_gate_reason == {
        "stage": "sizing_guard",
        "qty": 0.0,
        "p_lcb": stg.cfg["fallback_win_rate"],
        "sl_pips": 10.0,
    }
