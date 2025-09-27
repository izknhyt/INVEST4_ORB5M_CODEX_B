import unittest
from datetime import datetime, timedelta

from core.runner import BacktestRunner


class TestDataRobustness(unittest.TestCase):
    def make_bar(self, ts, spread=0.005, valid=True):
        if not valid:
            return {"timestamp": ts.isoformat(), "symbol": "USDJPY", "tf": "5m"}
        return {
            "timestamp": ts.isoformat(),
            "symbol": "USDJPY",
            "tf": "5m",
            "o": 150.0,
            "h": 150.2,
            "l": 149.8,
            "c": 150.1,
            "v": 0.0,
            "spread": spread,
        }

    def test_runner_skips_invalid_rows(self):
        start = datetime(2024, 1, 1, 8, 0)
        bars = [self.make_bar(start + timedelta(minutes=5*i)) for i in range(5)]
        bars.insert(2, self.make_bar(start + timedelta(minutes=10), valid=False))
        runner = BacktestRunner(equity=100_000.0, symbol="USDJPY")
        metrics = runner.run(bars)
        self.assertIsNotNone(metrics)

    def test_high_spread_blocks_trades(self):
        start = datetime(2024, 1, 1, 8, 0)
        bars = [self.make_bar(start + timedelta(minutes=5*i), spread=5.0) for i in range(10)]
        runner = BacktestRunner(equity=100_000.0, symbol="USDJPY")
        metrics = runner.run(bars)
        self.assertEqual(metrics.trades, 0)


if __name__ == "__main__":
    unittest.main()
