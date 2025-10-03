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
    assert strategy._pending_signal is None

    # Price keeps falling without retesting OR low. Previously the OR condition would
    # short-circuit and mark a retest; ensure it no longer does so.
    no_retest = {"h": 150.994, "l": 150.985}
    strategy.on_bar(_bar(150.994, 150.985, 150.988, [sell_break, no_retest]))
    assert strategy.state["waiting_retest"] is True
    assert strategy.state["retest_seen"] is False
    assert strategy._pending_signal is None

    # Proper retest that tags the OR low from below
    retest = {"h": 150.996, "l": 150.988}
    strategy.on_bar(_bar(150.996, 150.988, 150.989, [no_retest, retest]))
    assert not strategy.state["waiting_retest"]
    assert strategy.state["retest_seen"] is True
    assert strategy._pending_signal is None

    # Re-break to confirm entry
    confirm = {"h": 150.990, "l": 150.990 - 0.01}
    strategy.on_bar(_bar(confirm["h"], confirm["l"], 150.990 - 0.005, [retest, confirm]))
    assert strategy._pending_signal is not None
    assert strategy._pending_signal["side"] == "SELL"
