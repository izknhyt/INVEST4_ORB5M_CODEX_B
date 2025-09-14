import unittest

from core.fill_engine import BridgeFill, OrderSpec


class TestBridgeFill(unittest.TestCase):
    def test_buy_both_reachable_up_bias_prefers_tp(self):
        bf = BridgeFill()
        # Bar with strong up close (c >> o), both TP/SL reachable
        bar = {"o": 100.0, "h": 101.5, "l": 98.5, "c": 101.4, "pip": 0.01, "spread": 0.02}
        spec = OrderSpec(side="BUY", entry=100.5, tp_pips=50, sl_pips=50, slip_cap_pip=20)
        res = bf.simulate(bar, spec)
        self.assertTrue(res["fill"]) 
        self.assertIn("p_tp", res)
        self.assertGreater(res["p_tp"], 0.5)
        self.assertEqual(res["exit_reason"], "tp")

    def test_sell_both_reachable_down_bias_prefers_tp(self):
        bf = BridgeFill()
        # Down move (c << o), both reachable
        bar = {"o": 100.0, "h": 101.5, "l": 98.5, "c": 98.6, "pip": 0.01, "spread": 0.02}
        spec = OrderSpec(side="SELL", entry=99.5, tp_pips=50, sl_pips=50, slip_cap_pip=20)
        res = bf.simulate(bar, spec)
        self.assertTrue(res["fill"]) 
        self.assertIn("p_tp", res)
        self.assertGreater(res["p_tp"], 0.5)
        self.assertEqual(res["exit_reason"], "tp")

    def test_deterministic_single_side(self):
        bf = BridgeFill()
        # Only TP reachable for BUY
        bar = {"o": 100.0, "h": 101.0, "l": 99.9, "c": 100.8, "pip": 0.01, "spread": 0.02}
        spec = OrderSpec(side="BUY", entry=100.5, tp_pips=20, sl_pips=1000, slip_cap_pip=20)
        res = bf.simulate(bar, spec)
        self.assertTrue(res["fill"]) 
        self.assertEqual(res["p_tp"], 1.0)
        self.assertEqual(res["exit_reason"], "tp")


if __name__ == '__main__':
    unittest.main()

