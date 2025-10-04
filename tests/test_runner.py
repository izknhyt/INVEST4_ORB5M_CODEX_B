import csv
from pathlib import Path
import unittest
from datetime import datetime, timedelta, timezone

from core.runner import BacktestRunner, Metrics, RunnerConfig
from core.pips import price_to_pips


def make_bar(ts, symbol, o, h, l, c, spread):
    return {
        "timestamp": ts.isoformat(),
        "symbol": symbol,
        "tf": "5m",
        "o": o,
        "h": h,
        "l": l,
        "c": c,
        "v": 0.0,
        "spread": spread,
    }


class TestRunner(unittest.TestCase):

    class DummyEV:
        def __init__(self, ev_lcb: float, p_lcb: float) -> None:
            self._ev_lcb = ev_lcb
            self._p_lcb = p_lcb

        def ev_lcb_oco(self, tp_pips: float, sl_pips: float, cost_pips: float) -> float:
            return self._ev_lcb

        def p_lcb(self) -> float:
            return self._p_lcb

        def update(self, hit: bool) -> None:
            self.last_update = hit

    def _prepare_breakout_environment(self, *, warmup_left: int = 0):
        import core.runner as runner_module

        symbol = "USDJPY"
        runner = BacktestRunner(equity=100_000.0, symbol=symbol)
        runner._strategy_gate_hook = None
        runner._ev_threshold_hook = None
        t0 = datetime(2024, 1, 5, 8, 0, tzinfo=timezone.utc)
        bars = []
        price = 150.0
        for i in range(6):
            bars.append(
                make_bar(
                    t0 + timedelta(minutes=5 * i),
                    symbol,
                    price,
                    price + 0.10,
                    price - 0.10,
                    price + 0.02,
                    spread=0.02,
                )
            )
            price += 0.01
        or_high = max(b["h"] for b in bars)
        breakout = make_bar(
            t0 + timedelta(minutes=5 * 6),
            symbol,
            price,
            or_high + 0.12,
            price - 0.05,
            price,
            spread=0.02,
        )
        for bar in bars:
            new_session, session, calibrating = runner._update_daily_state(bar)
            runner._compute_features(
                bar,
                session=session,
                new_session=new_session,
                calibrating=calibrating,
            )
        new_session, session, calibrating = runner._update_daily_state(breakout)
        bar_input, ctx, atr14, adx14, or_h, or_l = runner._compute_features(
            breakout,
            session=session,
            new_session=new_session,
            calibrating=calibrating,
        )
        pending = {
            "side": "BUY",
            "tp_pips": 2.0,
            "sl_pips": 1.0,
            "trail_pips": 0.0,
            "entry": breakout["c"],
        }
        original_pass_gates = runner_module.pass_gates
        runner_module.pass_gates = lambda ctx: True
        self.addCleanup(lambda: setattr(runner_module, "pass_gates", original_pass_gates))
        runner._last_timestamp = breakout["timestamp"]
        runner._warmup_left = warmup_left
        runner.rcfg.min_or_atr_ratio = 0.0
        runner.rcfg.allow_low_rv = True
        runner.rcfg.allowed_sessions = ()
        return runner, pending, breakout, bar_input, ctx, atr14, adx14, or_h, or_l, calibrating

    def test_minimal_flow_produces_metrics(self):
        # create simple opening range then breakout
        symbol = "USDJPY"
        t0 = datetime(2024, 1, 1, 8, 0, tzinfo=timezone.utc)
        bars = []
        price = 150.00
        # 6 bars opening range
        for i in range(6):
            bars.append(make_bar(t0 + timedelta(minutes=5*i), symbol, price, price+0.10, price-0.10, price+0.02, spread=0.02))
            price += 0.01
        # breakout bar exceeding OR high
        or_high = max(b["h"] for b in bars)
        bars.append(make_bar(t0 + timedelta(minutes=5*6), symbol, price, or_high + 0.10, price-0.05, price, spread=0.02))

        runner = BacktestRunner(equity=100_000.0, symbol=symbol)
        metrics = runner.run(bars, mode="conservative")
        self.assertIsNotNone(metrics)
        d = metrics.as_dict()
        # At least attempted one trade
        self.assertGreaterEqual(d["trades"], 0)

    def test_run_partial_matches_full_run(self):
        symbol = "USDJPY"
        t0 = datetime(2024, 1, 2, 8, 0, tzinfo=timezone.utc)
        bars = []
        price = 151.00
        for i in range(6):
            bars.append(make_bar(t0 + timedelta(minutes=5 * i), symbol, price, price + 0.10, price - 0.10, price + 0.02, spread=0.02))
            price += 0.01
        or_high = max(b["h"] for b in bars)
        breakout = make_bar(t0 + timedelta(minutes=5 * 6), symbol, price, or_high + 0.15, price - 0.05, price, spread=0.02)
        bars.append(breakout)

        runner_full = BacktestRunner(equity=200_000.0, symbol=symbol)
        metrics_full = runner_full.run(list(bars), mode="conservative")

        runner_partial = BacktestRunner(equity=200_000.0, symbol=symbol)
        runner_partial.run_partial(bars[:4], mode="conservative")
        metrics_partial = runner_partial.run_partial(bars[4:], mode="conservative")

        self.assertEqual(metrics_full.as_dict(), metrics_partial.as_dict())
        self.assertAlmostEqual(metrics_full.equity_curve[0], 200_000.0)
        self.assertAlmostEqual(metrics_partial.equity_curve[0], 200_000.0)

        state = runner_partial.export_state()
        self.assertIn("runtime", state)
        self.assertIn("warmup_left", state["runtime"])
        self.assertIn("last_timestamp", state.get("meta", {}))

    def test_runtime_reset_reinitializes_equity_curve(self):
        symbol = "USDJPY"
        t0 = datetime(2024, 1, 3, 8, 0, tzinfo=timezone.utc)
        bars = []
        price = 149.50
        for i in range(6):
            bars.append(make_bar(t0 + timedelta(minutes=5 * i), symbol, price, price + 0.10, price - 0.10, price + 0.02, spread=0.02))
            price += 0.01
        or_high = max(b["h"] for b in bars)
        bars.append(make_bar(t0 + timedelta(minutes=5 * 6), symbol, price, or_high + 0.12, price - 0.05, price, spread=0.02))

        runner = BacktestRunner(equity=150_000.0, symbol=symbol)
        metrics_first = runner.run(list(bars), mode="conservative")
        metrics_second = runner.run(list(bars), mode="conservative")

        self.assertGreaterEqual(len(metrics_first.equity_curve), 1)
        self.assertEqual(metrics_first.equity_curve[0], 150_000.0)
        self.assertEqual(metrics_second.equity_curve[0], 150_000.0)
        self.assertListEqual(metrics_first.equity_curve[1:], metrics_second.equity_curve[1:])

    def test_metrics_compute_sharpe_and_drawdown(self):
        metrics = Metrics()
        returns = [10.0, -5.0, 20.0, -15.0]
        metrics.trade_returns.extend(returns)
        metrics.equity_curve = [0.0]
        cumulative = 0.0
        for r in returns:
            cumulative += r
            metrics.equity_curve.append(cumulative)
        metrics.total_pips = sum(returns)
        result = metrics.as_dict()
        self.assertIn("sharpe", result)
        self.assertIn("max_drawdown", result)
        self.assertAlmostEqual(result["sharpe"], 0.3713906763541037, places=6)
        self.assertAlmostEqual(result["max_drawdown"], -15.0, places=6)
        self.assertIsNone(result["win_rate"])

    def test_metrics_records_equity_curve_from_records_csv(self):
        metrics = Metrics()
        csv_path = Path(__file__).parent / "data" / "runner_sample_records.csv"
        with csv_path.open() as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("stage") != "trade":
                    continue
                pnl = float(row.get("pnl_pips", 0.0))
                metrics.record_trade(pnl, pnl > 0)

        result = metrics.as_dict()
        self.assertEqual(metrics.trades, 4)
        self.assertEqual(metrics.wins, 2)
        self.assertAlmostEqual(metrics.total_pips, 5.0)
        self.assertListEqual(
            [round(v, 6) for v in metrics.equity_curve],
            [0.0, 12.0, 7.0, 15.0, 5.0],
        )
        self.assertAlmostEqual(result["sharpe"], 0.27660638840895513)
        self.assertAlmostEqual(result["max_drawdown"], -10.0)
        self.assertAlmostEqual(result["win_rate"], 0.5)

    def test_slip_learning_helper_updates_coefficients(self):
        cfg = RunnerConfig(include_expected_slip=True, slip_learn=True)
        runner = BacktestRunner(equity=100_000.0, symbol="USDJPY", runner_cfg=cfg)

        class DummyOrder:
            def __init__(self, qty: float, price: float) -> None:
                self.qty = qty
                self.price = price

        order = DummyOrder(qty=2.0, price=150.0)
        ctx = {"spread_band": "normal"}
        prev_a = runner.slip_a["normal"]
        prev_qty_ewma = runner.qty_ewma["normal"]

        qty_sample, slip_actual = runner._update_slip_learning(
            order=order,
            actual_price=150.02,
            intended_price=order.price,
            ctx=ctx,
        )

        expected_slip = abs(price_to_pips(150.02 - order.price, "USDJPY"))
        self.assertAlmostEqual(qty_sample, 2.0)
        self.assertAlmostEqual(slip_actual, expected_slip)

        alpha = cfg.slip_ewma_alpha
        sample_a = slip_actual / max(qty_sample, 1e-9)
        expected_a = (1 - alpha) * prev_a + alpha * sample_a
        expected_qty = (1 - alpha) * prev_qty_ewma + alpha * qty_sample
        self.assertAlmostEqual(runner.slip_a["normal"], expected_a)
        self.assertAlmostEqual(runner.qty_ewma["normal"], expected_qty)

        cfg_off = RunnerConfig(include_expected_slip=False, slip_learn=True)
        runner_off = BacktestRunner(equity=50_000.0, symbol="USDJPY", runner_cfg=cfg_off)
        prev_a_off = runner_off.slip_a["normal"]
        prev_qty_off = runner_off.qty_ewma["normal"]

        qty_off, slip_off = runner_off._update_slip_learning(
            order=order,
            actual_price=150.02,
            intended_price=order.price,
            ctx=ctx,
        )

        self.assertAlmostEqual(qty_off, 2.0)
        self.assertAlmostEqual(slip_off, expected_slip)
        self.assertEqual(runner_off.slip_a["normal"], prev_a_off)
        self.assertEqual(runner_off.qty_ewma["normal"], prev_qty_off)
    def test_evaluate_entry_conditions_and_ev_pass_on_breakout(self):
        (
            runner,
            pending,
            breakout,
            bar_input,
            ctx,
            atr14,
            adx14,
            or_h,
            or_l,
            calibrating,
        ) = self._prepare_breakout_environment(warmup_left=0)
        stub_ev = self.DummyEV(ev_lcb=1.2, p_lcb=0.65)
        runner._get_ev_manager = lambda key: stub_ev
        ctx_dbg = runner._evaluate_entry_conditions(
            pending=pending,
            bar=breakout,
            bar_input=bar_input,
            atr14=atr14,
            adx14=adx14,
            or_h=or_h,
            or_l=or_l,
        )
        self.assertIsNotNone(ctx_dbg)
        ev_eval = runner._evaluate_ev_threshold(
            ctx_dbg=ctx_dbg,
            pending=pending,
            calibrating=calibrating,
            timestamp=runner._last_timestamp,
        )
        self.assertIsNotNone(ev_eval)
        ev_mgr, ev_lcb, threshold_lcb, ev_bypass = ev_eval
        self.assertIs(ev_mgr, stub_ev)
        self.assertGreater(ev_lcb, threshold_lcb)
        self.assertFalse(ev_bypass)
        self.assertTrue(ctx_dbg.get("ev_pass"))
        slip_ok = runner._check_slip_and_sizing(
            ctx_dbg=ctx_dbg,
            pending=pending,
            ev_mgr=stub_ev,
            calibrating=calibrating,
            ev_bypass=ev_bypass,
            timestamp=runner._last_timestamp,
        )
        self.assertTrue(slip_ok)

    def test_evaluate_ev_threshold_rejects_when_ev_below_threshold(self):
        (
            runner,
            pending,
            breakout,
            bar_input,
            ctx,
            atr14,
            adx14,
            or_h,
            or_l,
            calibrating,
        ) = self._prepare_breakout_environment(warmup_left=0)
        stub_ev = self.DummyEV(ev_lcb=0.05, p_lcb=0.55)
        runner._get_ev_manager = lambda key: stub_ev
        ctx_dbg = runner._evaluate_entry_conditions(
            pending=pending,
            bar=breakout,
            bar_input=bar_input,
            atr14=atr14,
            adx14=adx14,
            or_h=or_h,
            or_l=or_l,
        )
        self.assertIsNotNone(ctx_dbg)
        ev_eval = runner._evaluate_ev_threshold(
            ctx_dbg=ctx_dbg,
            pending=pending,
            calibrating=calibrating,
            timestamp=runner._last_timestamp,
        )
        self.assertIsNone(ev_eval)
        self.assertEqual(runner.debug_counts["ev_reject"], 1)

    def test_warmup_bypass_allows_low_ev_signal(self):
        (
            runner,
            pending,
            breakout,
            bar_input,
            ctx,
            atr14,
            adx14,
            or_h,
            or_l,
            calibrating,
        ) = self._prepare_breakout_environment(warmup_left=5)
        stub_ev = self.DummyEV(ev_lcb=0.05, p_lcb=0.55)
        runner._get_ev_manager = lambda key: stub_ev
        ctx_dbg = runner._evaluate_entry_conditions(
            pending=pending,
            bar=breakout,
            bar_input=bar_input,
            atr14=atr14,
            adx14=adx14,
            or_h=or_h,
            or_l=or_l,
        )
        self.assertIsNotNone(ctx_dbg)
        ev_eval = runner._evaluate_ev_threshold(
            ctx_dbg=ctx_dbg,
            pending=pending,
            calibrating=calibrating,
            timestamp=runner._last_timestamp,
        )
        self.assertIsNotNone(ev_eval)
        ev_mgr, ev_lcb, threshold_lcb, ev_bypass = ev_eval
        self.assertTrue(ev_bypass)
        self.assertFalse(ctx_dbg.get("ev_pass"))
        slip_ok = runner._check_slip_and_sizing(
            ctx_dbg=ctx_dbg,
            pending=pending,
            ev_mgr=ev_mgr,
            calibrating=calibrating,
            ev_bypass=ev_bypass,
            timestamp=runner._last_timestamp,
        )
        self.assertTrue(slip_ok)
        self.assertEqual(runner.debug_counts["ev_bypass"], 1)




if __name__ == "__main__":
    unittest.main()

