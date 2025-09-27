import json
import tempfile
import unittest
from pathlib import Path

from scripts import report_benchmark_summary as rbs


class TestReportBenchmarkSummary(unittest.TestCase):
    def test_compute_summary_includes_extended_metrics(self):
        metrics = {
            "trades": 10,
            "wins": 6,
            "total_pips": 50.0,
            "sharpe": 1.2,
            "max_drawdown": 30.5,
        }
        summary = rbs.compute_summary(metrics)
        self.assertIn("sharpe", summary)
        self.assertIn("max_drawdown", summary)
        self.assertEqual(summary["sharpe"], 1.2)
        self.assertEqual(summary["max_drawdown"], 30.5)

    def test_main_emits_threshold_warnings(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            reports_dir = base_dir
            baseline_dir = reports_dir / "baseline"
            rolling_dir = reports_dir / "rolling"
            baseline_dir.mkdir(parents=True)
            (rolling_dir / "30").mkdir(parents=True)

            baseline_metrics = {
                "trades": 20,
                "wins": 10,
                "total_pips": -25.0,
                "sharpe": 0.5,
                "max_drawdown": -60.0,
            }
            rolling_metrics = {
                "trades": 15,
                "wins": 8,
                "total_pips": -10.0,
                "sharpe": 0.6,
                "max_drawdown": -55.0,
            }

            baseline_path = baseline_dir / "USDJPY_conservative.json"
            baseline_path.write_text(json.dumps(baseline_metrics))

            rolling_path = rolling_dir / "30" / "USDJPY_conservative.json"
            rolling_path.write_text(json.dumps(rolling_metrics))

            output_path = reports_dir / "benchmark_summary.json"

            args = [
                "--symbol",
                "USDJPY",
                "--mode",
                "conservative",
                "--reports-dir",
                str(reports_dir),
                "--windows",
                "30",
                "--json-out",
                str(output_path),
                "--min-sharpe",
                "0.8",
                "--max-drawdown",
                "40",
            ]

            rc = rbs.main(args)
            self.assertEqual(rc, 0)
            payload = json.loads(output_path.read_text())
            self.assertGreaterEqual(len(payload["warnings"]), 2)
            joined = " ".join(payload["warnings"])
            self.assertIn("baseline sharpe", joined)
            self.assertIn("rolling window 30 max_drawdown", joined)


if __name__ == "__main__":
    unittest.main()
