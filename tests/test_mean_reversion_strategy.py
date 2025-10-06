import unittest

from core.sizing import compute_qty_from_ctx
from strategies.mean_reversion import MeanReversionStrategy


class DummyEV:
    def __init__(self, p_lcb: float) -> None:
        self._p_lcb = p_lcb

    def p_lcb(self) -> float:
        return self._p_lcb


class MeanReversionStrategyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.strategy = MeanReversionStrategy()
        cfg = {
            "zscore_threshold": 1.2,
            "tp_atr_mult": 0.8,
            "sl_atr_mult": 1.0,
            "sl_over_tp": 1.1,
            "allow_high_rv": False,
        }
        self.strategy.on_start(cfg, ["USDJPY"], {})

    def _base_ctx(self) -> dict:
        return {
            "session": "LDN",
            "spread_band": "narrow",
            "rv_band": "mid",
            "allowed_sessions": ["LDN", "NY"],
            "allow_low_rv": True,
            "equity": 100000.0,
            "pip_value": 10.0,
            "sizing_cfg": {
                "risk_per_trade_pct": 0.25,
                "kelly_fraction": 0.25,
                "units_cap": 5.0,
                "max_trade_loss_pct": 0.5,
            },
            "ev_mode": "lcb",
            "ev_oco": DummyEV(0.7),
            "warmup_left": 0,
            "cost_pips": 0.4,
            "expected_slip_pip": 0.0,
            "size_floor_mult": 0.01,
            "cooldown_bars": 0,
        }

    def test_emits_order_with_atr_defaults(self) -> None:
        bar = {"c": 150.1, "atr14": 0.2, "zscore": 2.0}
        self.strategy.on_bar(bar)
        self.assertIsNotNone(self.strategy._pending_signal)
        ctx = self._base_ctx()
        self.assertTrue(self.strategy.strategy_gate(ctx, self.strategy._pending_signal))
        self.strategy.update_context(ctx)
        intents = list(self.strategy.signals())
        self.assertEqual(len(intents), 1)
        intent = intents[0]
        self.assertEqual(intent.side, "SELL")
        self.assertGreater(intent.oco["tp_pips"], 0.0)
        self.assertGreater(intent.oco["sl_pips"], intent.oco["tp_pips"])
        self.assertEqual(self.strategy.state["last_signal_bar"], self.strategy.state["bar_idx"])

        expected_qty = compute_qty_from_ctx(
            ctx,
            intent.oco["sl_pips"],
            mode="production",
            tp_pips=intent.oco["tp_pips"],
            p_lcb=ctx["ev_oco"].p_lcb(),
        )
        self.assertAlmostEqual(intent.qty, expected_qty)

    def test_strategy_gate_blocks_high_rv_and_adx(self) -> None:
        bar = {"c": 150.0, "atr14": 0.15, "zscore": -2.0}
        self.strategy.on_bar(bar)
        pending = self.strategy._pending_signal
        ctx = self._base_ctx()
        ctx["rv_band"] = "high"
        allowed = self.strategy.strategy_gate(ctx, pending)
        self.assertFalse(allowed)
        self.assertEqual(self.strategy._last_gate_reason["stage"], "rv_filter")
        ctx["rv_band"] = "mid"
        self.strategy.state["last_adx"] = 40.0
        allowed = self.strategy.strategy_gate(ctx, pending)
        self.assertFalse(allowed)
        self.assertEqual(self.strategy._last_gate_reason["stage"], "adx_filter")

    def test_ev_threshold_responds_to_zscore_and_profiles(self) -> None:
        bar = {"c": 150.0, "atr14": 0.15, "zscore": -2.5}
        self.strategy.on_bar(bar)
        pending = self.strategy._pending_signal
        ctx = self._base_ctx()
        ctx["ev_profile_stats"] = {
            "recent": {"p_mean": 0.75, "observations": 12},
            "long_term": {"p_mean": 0.7, "observations": 40},
        }
        low_threshold = self.strategy.ev_threshold(ctx, pending, 0.5)
        ctx["ev_profile_stats"] = None
        pending["zscore"] = 1.0
        high_threshold = self.strategy.ev_threshold(ctx, pending, 0.5)
        self.assertLess(low_threshold, 0.5)
        self.assertGreater(high_threshold, 0.5)


if __name__ == "__main__":
    unittest.main()
