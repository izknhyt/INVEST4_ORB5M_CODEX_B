import unittest

from scripts.report_benchmark_summary import compute_summary


class TestReportBenchmarkSummary(unittest.TestCase):
    def test_compute_summary_includes_extended_metrics(self):
        metrics = {
            "trades": 10,
            "wins": 6,
            "total_pips": 50.0,
            "sharpe": 1.2,
            "max_drawdown": 30.5,
        }
        summary = compute_summary(metrics)
        self.assertIn("sharpe", summary)
        self.assertIn("max_drawdown", summary)
        self.assertEqual(summary["sharpe"], 1.2)
        self.assertEqual(summary["max_drawdown"], 30.5)


if __name__ == "__main__":
    unittest.main()
