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
                "--min-win-rate",
                "0.55",
                "--max-drawdown",
                "40",
            ]

            rc = rbs.main(args)
            self.assertEqual(rc, 0)
            payload = json.loads(output_path.read_text())
            self.assertGreaterEqual(len(payload["warnings"]), 3)
            joined = " ".join(payload["warnings"])
            self.assertIn("baseline sharpe", joined)
            self.assertIn("baseline win_rate", joined)
            self.assertIn("rolling window 30 win_rate", joined)
            self.assertIn("rolling window 30 max_drawdown", joined)
            alerts = payload.get("threshold_alerts", [])
            self.assertGreaterEqual(len(alerts), 3)
            sharpe_alerts = [a for a in alerts if a["metric"] == "sharpe"]
            drawdown_alerts = [a for a in alerts if a["metric"] == "max_drawdown"]
            win_rate_alerts = [a for a in alerts if a["metric"] == "win_rate"]
            self.assertTrue(sharpe_alerts, msg=f"Expected sharpe alert, got {alerts}")
            self.assertTrue(drawdown_alerts, msg=f"Expected drawdown alert, got {alerts}")
            self.assertTrue(win_rate_alerts, msg=f"Expected win_rate alert, got {alerts}")
            self.assertEqual(sharpe_alerts[0]["comparison"], "lt")
            self.assertEqual(drawdown_alerts[0]["comparison"], "gt_abs")
            self.assertEqual(win_rate_alerts[0]["comparison"], "lt")

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
                "--min-win-rate",
                "0.55",
                "--max-drawdown",
                "-200",
            ]

            with self.assertLogs(rbs.LOGGER, level="WARNING") as log_ctx:
                rc = rbs.main(args_with_negative_threshold)
            self.assertEqual(rc, 0)
            payload = json.loads(output_path.read_text())
            joined = " ".join(payload["warnings"])
            self.assertNotIn("max_drawdown", joined)
            self.assertIn("win_rate", joined)
            alerts_after_normalization = payload.get("threshold_alerts", [])
            self.assertTrue(alerts_after_normalization)
            self.assertFalse(
                [a for a in alerts_after_normalization if a["metric"] == "max_drawdown"],
                msg=f"Drawdown alerts should be cleared when threshold is large: {alerts_after_normalization}",
            )
            self.assertTrue(
                any("negative --max-drawdown" in message for message in log_ctx.output),
                msg=f"Expected normalization warning in logs, got {log_ctx.output}",
            )

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
                    "--min-win-rate",
                    "0.55",
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
            alerts = payload.get("threshold_alerts", [])
            self.assertTrue(any(alert["metric"] == "win_rate" for alert in alerts))

    def test_main_skips_plot_when_matplotlib_missing(self):
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
                "total_pips": 5.0,
                "sharpe": 0.4,
                "max_drawdown": -10.0,
            }
            rolling_metrics = {
                "trades": 15,
                "wins": 8,
                "total_pips": 3.0,
                "sharpe": 0.3,
                "max_drawdown": -8.0,
            }

            (baseline_dir / "USDJPY_conservative.json").write_text(json.dumps(baseline_metrics))
            (rolling_dir / "30" / "USDJPY_conservative.json").write_text(json.dumps(rolling_metrics))

            output_path = reports_dir / "benchmark_summary.json"
            plot_path = reports_dir / "benchmark_summary.png"

            original_import = __import__

            def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
                if name.startswith("matplotlib") or name == "pandas":
                    raise ModuleNotFoundError(name)
                return original_import(name, globals, locals, fromlist, level)

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
                "--plot-out",
                str(plot_path),
            ]

            with mock.patch("builtins.__import__", side_effect=fake_import):
                rc = rbs.main(args)

            self.assertEqual(rc, 0)
            payload = json.loads(output_path.read_text())
            self.assertIn("summary plot skipped", " ".join(payload["warnings"]))
            self.assertFalse(plot_path.exists(), msg="plot should not be created when dependencies missing")


if __name__ == "__main__":
    unittest.main()
