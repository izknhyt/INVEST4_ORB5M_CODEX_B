import unittest

from core.ev_gate import BetaBinomialEV
from core.sizing import SizingConfig, base_units, kelly_multiplier_oco, apply_guards
from strategies.day_orb_5m import DayORB5m


class TestEVSizing(unittest.TestCase):
    def test_beta_binomial_ev_lcb(self):
        ev = BetaBinomialEV(conf_level=0.95, decay=0.0)  # plain counts
        # 80 hits, 20 misses
        for _ in range(80):
            ev.update(True)
        for _ in range(20):
            ev.update(False)
        val = ev.ev_lcb_oco(tp_pips=1.0, sl_pips=1.0, cost_pips=0.0)
        # Wilson-LCB is conservative; just ensure positive EV under strong edge
        self.assertGreater(val, 0.0)

    def test_sizing_guards(self):
        cfg = SizingConfig(risk_per_trade_pct=0.25, kelly_fraction=0.25, units_cap=5.0, max_trade_loss_pct=0.5)
        equity = 100_000.0
        pip_value = 10.0
        sl_pips = 20.0
        base = base_units(equity, pip_value, sl_pips, cfg)
        mult = kelly_multiplier_oco(p_lcb=0.7, tp_pips=25.0, sl_pips=20.0, cfg=cfg)
        qty = apply_guards(base * mult, equity, pip_value, sl_pips, cfg)
        self.assertGreater(qty, 0.0)


class TestStrategyIntegration(unittest.TestCase):
    def test_strategy_emits_order_with_qty(self):
        # Prepare strategy
        stg = DayORB5m()
        cfg = {"or_n": 6, "k_tp": 1.0, "k_sl": 0.8, "k_tr": 0.0}
        stg.on_start(cfg, ["USDJPY"], {})

        # Create OR window bars and a breakout bar
        window = []
        price = 150.00
        for i in range(6):
            window.append({"o": price, "h": price + 0.10, "l": price - 0.10, "c": price + 0.05})
            price += 0.01
        or_h = max(b["h"] for b in window)
        breakout_bar = {"o": price, "h": or_h + 0.05, "l": price - 0.05, "c": price, "atr14": 10.0, "window": window}

        # EV estimator with high success probability
        ev = BetaBinomialEV(conf_level=0.95, decay=0.0)
        for _ in range(90):
            ev.update(True)
        for _ in range(10):
            ev.update(False)

        ctx = {
            "session": "LDN",
            "spread_band": "normal",
            "rv_band": "mid",
            "expected_slip_pip": 0.2,
            "slip_cap_pip": 1.5,
            "ev_oco": ev,
            "cost_pips": 0.1,
            "threshold_lcb_pip": 0.5,
            "equity": 100_000.0,
            "pip_value": 10.0,
            "sizing_cfg": {
                "risk_per_trade_pct": 0.25,
                "kelly_fraction": 0.25,
                "units_cap": 5.0,
                "max_trade_loss_pct": 0.5,
            },
        }

        # Attach ctx and emit
        stg.cfg["ctx"] = ctx
        stg.on_bar(breakout_bar)
        sigs = list(stg.signals())
        self.assertEqual(len(sigs), 1)
        self.assertGreater(sigs[0].qty, 0.0)
        self.assertIn("oco", sigs[0].__dict__)


if __name__ == "__main__":
    unittest.main()
