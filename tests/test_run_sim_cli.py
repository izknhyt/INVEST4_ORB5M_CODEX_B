import csv
import json
import os
import sys
import tempfile
import textwrap
import types
import unittest
from unittest import mock

from core.sizing import compute_qty_from_ctx
from core.runner import RunnerConfig
from scripts.run_sim import load_bars_csv, main as run_sim_main
from strategies.mean_reversion import MeanReversionStrategy


CSV_CONTENT = """timestamp,symbol,tf,o,h,l,c,v,spread,zscore
2024-01-01T08:00:00Z,USDJPY,5m,150.00,150.10,149.90,150.02,0,0.02,0.0
2024-01-01T08:05:00Z,USDJPY,5m,150.01,150.11,149.91,150.03,0,0.02,0.3
2024-01-01T08:10:00Z,USDJPY,5m,150.02,150.12,149.92,150.04,0,0.02,0.8
2024-01-01T08:15:00Z,USDJPY,5m,150.03,150.13,149.93,150.05,0,0.02,-0.7
2024-01-01T08:20:00Z,USDJPY,5m,150.04,150.14,149.94,150.06,0,0.02,0.6
2024-01-01T08:25:00Z,USDJPY,5m,150.05,150.15,149.95,150.07,0,0.02,-1.2
2024-01-01T08:30:00Z,USDJPY,5m,150.06,150.30,149.95,150.10,0,0.02,0.4
"""


class TestRunSimCLI(unittest.TestCase):
    def test_load_bars_csv(self):
        path = os.path.join(os.path.dirname(__file__), "_tmp_bars.csv")
        with open(path, "w") as f:
            f.write(CSV_CONTENT)
        try:
            bars = load_bars_csv(path)
            self.assertGreaterEqual(len(bars), 7)
            self.assertEqual(bars[0]["tf"], "5m")
            self.assertEqual(bars[0]["symbol"], "USDJPY")
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    def test_run_sim_outputs_extended_metrics(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "bars.csv")
            with open(csv_path, "w", encoding="utf-8") as f:
                f.write(CSV_CONTENT)
            json_out = os.path.join(tmpdir, "metrics.json")
            args = [
                "--csv", csv_path,
                "--symbol", "USDJPY",
                "--mode", "conservative",
                "--equity", "100000",
                "--json-out", json_out,
                "--dump-max", "0",
                "--no-auto-state",
                "--no-ev-profile",
                "--no-aggregate-ev",
            ]
            rc = run_sim_main(args)
            self.assertEqual(rc, 0)
            with open(json_out, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertIn("sharpe", data)
            self.assertIn("max_drawdown", data)

    def test_run_sim_respects_time_window(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "bars.csv")
            with open(csv_path, "w", encoding="utf-8") as f:
                f.write(CSV_CONTENT)
            json_out = os.path.join(tmpdir, "metrics.json")
            args = [
                "--csv", csv_path,
                "--symbol", "USDJPY",
                "--mode", "conservative",
                "--equity", "100000",
                "--json-out", json_out,
                "--dump-max", "0",
                "--no-auto-state",
                "--no-ev-profile",
                "--no-aggregate-ev",
                "--start-ts", "2024-01-01T08:10:00Z",
                "--end-ts", "2024-01-01T08:20:00Z",
            ]
            backtest_runner_cls = run_sim_main.__globals__["BacktestRunner"]
            original_run = backtest_runner_cls.run
            captured = {}

            def _wrapped(self, bars, *run_args, **run_kwargs):
                captured["bars"] = bars
                return original_run(self, bars, *run_args, **run_kwargs)

            with mock.patch.object(backtest_runner_cls, "run", autospec=True, side_effect=_wrapped) as patched_run:
                rc = run_sim_main(args)
            self.assertEqual(rc, 0)
            patched_run.assert_called_once()
            bars_arg = captured.get("bars")
            self.assertIsNotNone(bars_arg)
            self.assertEqual(len(bars_arg), 3)
            with open(json_out, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertIn("sharpe", data)
            self.assertIn("max_drawdown", data)

    def test_run_sim_manifest_mean_reversion(self):
        manifest_yaml = textwrap.dedent(
            """
            meta:
              id: mean_reversion_v1
              name: Mean Reversion (USDJPY)
              version: "1.0"
              category: day
            strategy:
              class_path: strategies.mean_reversion.MeanReversionStrategy
              instruments:
                - symbol: USDJPY
                  timeframe: 5m
                  mode: conservative
              parameters:
                or_n: 2
                cooldown_bars: 1
                zscore_threshold: 1.0
                tp_atr_mult: 0.8
                sl_atr_mult: 1.0
                min_tp_pips: 4.0
                min_sl_pips: 8.0
                sl_over_tp: 1.1
                allow_high_rv: true
                allow_mid_rv: true
                allow_low_rv: true
                max_adx: 28.0
            router:
              allowed_sessions: [LDN, NY]
            risk:
              risk_per_trade_pct: 0.1
              max_daily_dd_pct: 8.0
              notional_cap: 500000
              max_concurrent_positions: 1
              warmup_trades: 0
            runner:
              runner_config:
                threshold_lcb_pip: 0.0
                min_or_atr_ratio: 0.0
                allowed_sessions: [LDN, NY]
                allow_low_rv: true
                spread_bands:
                  narrow: 3.0
                  normal: 5.0
                  wide: 99.0
                warmup_trades: 0
            state:
              archive_namespace: strategies.mean_reversion.MeanReversionStrategy/USDJPY/conservative
            """
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "bars.csv")
            with open(csv_path, "w", encoding="utf-8") as f:
                f.write(CSV_CONTENT)
            manifest_path = os.path.join(tmpdir, "manifest.yaml")
            with open(manifest_path, "w", encoding="utf-8") as f:
                f.write(manifest_yaml)
            json_out = os.path.join(tmpdir, "metrics.json")

            gate_cfgs = []
            threshold_cfgs = []
            qty_checks = []
            original_gate = MeanReversionStrategy.strategy_gate
            original_threshold = MeanReversionStrategy.ev_threshold
            original_signals = MeanReversionStrategy.signals

            def _gate_wrapper(self, ctx, pending):
                gate_cfgs.append(dict(self.cfg))
                return original_gate(self, ctx, pending)

            def _threshold_wrapper(self, ctx, pending, base_threshold):
                threshold_cfgs.append(dict(self.cfg))
                return original_threshold(self, ctx, pending, base_threshold)

            args = [
                "--csv", csv_path,
                "--equity", "100000",
                "--json-out", json_out,
                "--strategy-manifest", manifest_path,
                "--dump-max", "0",
                "--no-auto-state",
                "--no-ev-profile",
                "--no-aggregate-ev",
            ]

            def _signals_wrapper(self):
                intents = original_signals(self)
                ctx = dict(self.cfg.get("ctx", {}))
                if intents and ctx.get("ev_oco") is not None:
                    sig = intents[0]
                    expected = compute_qty_from_ctx(
                        ctx,
                        sig.oco["sl_pips"],
                        mode="production",
                        tp_pips=sig.oco["tp_pips"],
                        p_lcb=ctx["ev_oco"].p_lcb(),
                    )
                    qty_checks.append((sig.qty, expected))
                return intents

            with mock.patch.object(MeanReversionStrategy, "strategy_gate", autospec=True, side_effect=_gate_wrapper) as gate_mock:
                with mock.patch.object(MeanReversionStrategy, "ev_threshold", autospec=True, side_effect=_threshold_wrapper) as threshold_mock:
                    with mock.patch.object(MeanReversionStrategy, "signals", autospec=True, side_effect=_signals_wrapper) as signals_mock:
                        rc = run_sim_main(args)

            self.assertEqual(rc, 0)
            gate_mock.assert_called()
            threshold_mock.assert_called()
            self.assertTrue(gate_cfgs)
            self.assertTrue(threshold_cfgs)
            for cfg in gate_cfgs + threshold_cfgs:
                self.assertIn("allow_high_rv", cfg)
                self.assertTrue(cfg["allow_high_rv"])
                self.assertIn("zscore_threshold", cfg)
            for qty, expected in qty_checks:
                self.assertAlmostEqual(qty, expected)
            with open(json_out, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertIn("sharpe", data)
            self.assertIn("max_drawdown", data)

    @mock.patch("scripts.run_sim.BacktestRunner")
    def test_run_sim_cli_applies_fill_overrides(self, mock_runner):
        class DummyMetrics:
            def __init__(self):
                self.records = []
                self.daily = {}
                self.runtime = {}
                self.debug = {}

            def as_dict(self):
                return {"trades": 0, "wins": 0, "total_pips": 0.0}

        mock_instance = mock_runner.return_value
        mock_instance.strategy_cls = MeanReversionStrategy
        mock_instance.ev_global = types.SimpleNamespace(decay=0.02)
        mock_instance.run.return_value = DummyMetrics()

        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "bars.csv")
            with open(csv_path, "w", encoding="utf-8") as f:
                f.write(CSV_CONTENT)
            json_out = os.path.join(tmpdir, "metrics.json")
            args = [
                "--csv", csv_path,
                "--symbol", "USDJPY",
                "--mode", "bridge",
                "--equity", "100000",
                "--json-out", json_out,
                "--dump-max", "0",
                "--fill-same-bar-policy", "tp_first",
                "--fill-same-bar-policy-bridge", "sl_first",
                "--fill-bridge-lambda", "0.7",
                "--fill-bridge-drift-scale", "1.1",
                "--no-auto-state",
                "--no-ev-profile",
                "--no-aggregate-ev",
            ]

            rc = run_sim_main(args)
            self.assertEqual(rc, 0)

            self.assertTrue(mock_runner.called)
            call_args = mock_runner.call_args
            self.assertIsNotNone(call_args)
            rcfg = call_args.kwargs.get("runner_cfg")
            self.assertIsInstance(rcfg, RunnerConfig)
            self.assertEqual(rcfg.fill_same_bar_policy_conservative, "tp_first")
            self.assertEqual(rcfg.fill_same_bar_policy_bridge, "sl_first")
            self.assertAlmostEqual(rcfg.fill_bridge_lambda, 0.7)
            self.assertAlmostEqual(rcfg.fill_bridge_drift_scale, 1.1)

    def test_run_sim_debug_records_capture_hook_failures(self):
        csv_fixture = os.path.join(os.path.dirname(__file__), "data", "hook_failure_fixture.csv")
        self.assertTrue(os.path.exists(csv_fixture))

        from tests.fixtures.strategies.forced_failure import DeterministicFailureStrategy

        module_name = "strategies.tests.fixtures.strategies.forced_failure"
        alias = types.ModuleType(module_name)
        alias.DeterministicFailureStrategy = DeterministicFailureStrategy
        sys.modules[module_name] = alias
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                json_out = os.path.join(tmpdir, "metrics.json")
                dump_csv = os.path.join(tmpdir, "records.csv")
                args = [
                    "--csv", csv_fixture,
                    "--symbol", "USDJPY",
                    "--mode", "conservative",
                    "--equity", "100000",
                    "--json-out", json_out,
                    "--debug",
                    "--dump-max", "5",
                    "--dump-csv", dump_csv,
                    "--no-auto-state",
                    "--no-ev-profile",
                    "--no-aggregate-ev",
                    "--strategy", "tests.fixtures.strategies.forced_failure.DeterministicFailureStrategy",
                ]
                rc = run_sim_main(args)
                self.assertEqual(rc, 0)

                with open(json_out, "r", encoding="utf-8") as f:
                    data = json.load(f)
                debug = data.get("debug")
                self.assertIsNotNone(debug)
                self.assertGreaterEqual(debug.get("strategy_gate_error", 0), 1)
                self.assertGreaterEqual(debug.get("ev_threshold_error", 0), 1)
                self.assertEqual(data.get("dump_csv"), dump_csv)
                self.assertGreaterEqual(int(data.get("dump_rows", 0)), 2)

                with open(dump_csv, "r", encoding="utf-8") as f:
                    rows = list(csv.DictReader(f))

                self.assertTrue(any(row.get("stage") == "strategy_gate_error" for row in rows))
                self.assertTrue(any(row.get("stage") == "ev_threshold_error" for row in rows))

                gate_row = next(row for row in rows if row.get("stage") == "strategy_gate_error")
                gate_keys = {k for k, v in gate_row.items() if v not in (None, "")}
                self.assertEqual(gate_keys, {"stage", "ts", "side", "error"})

                threshold_row = next(row for row in rows if row.get("stage") == "ev_threshold_error")
                threshold_keys = {k for k, v in threshold_row.items() if v not in (None, "")}
                self.assertEqual(threshold_keys, {"stage", "ts", "side", "base_threshold", "error"})
        finally:
            sys.modules.pop(module_name, None)


if __name__ == "__main__":
    unittest.main()
