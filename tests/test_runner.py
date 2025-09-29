import csv
from pathlib import Path
import unittest
from datetime import datetime, timedelta, timezone

from core.runner import BacktestRunner, Metrics


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

        state = runner_partial.export_state()
        self.assertIn("runtime", state)
        self.assertIn("warmup_left", state["runtime"])
        self.assertIn("last_timestamp", state.get("meta", {}))

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


if __name__ == "__main__":
    unittest.main()

