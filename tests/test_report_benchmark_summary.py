import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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

            args_with_negative_threshold = [
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
                "-200",
            ]

            rc = rbs.main(args_with_negative_threshold)
            self.assertEqual(rc, 0)
            payload = json.loads(output_path.read_text())
            joined = " ".join(payload["warnings"])
            self.assertNotIn("max_drawdown", joined)

    def test_main_sends_webhook_when_warnings_present(self):
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

            with mock.patch.object(rbs, "_post_webhook", return_value=(True, "status=200")) as post_hook:
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
                    "--webhook",
                    "https://example.com/hook",
                ]

                rc = rbs.main(args)
                self.assertEqual(rc, 0)
                self.assertEqual(post_hook.call_count, 1)

            payload = json.loads(output_path.read_text())
            self.assertIn("webhook", payload)
            assert payload["webhook"]["targets"] == ["https://example.com/hook"]
            deliveries = payload["webhook"]["deliveries"]
            self.assertEqual(len(deliveries), 1)
            self.assertTrue(deliveries[0]["ok"])


if __name__ == "__main__":
    unittest.main()
