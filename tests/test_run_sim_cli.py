import csv
import json
import os
import sys
import tempfile
import textwrap
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from core.sizing import compute_qty_from_ctx
from core.runner import RunnerConfig
from core.runner_execution import RunnerExecutionManager
from core.runner_lifecycle import RunnerLifecycleManager
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


CSV_CONTENT_WITH_BLANK_SPREAD = textwrap.dedent(
    """\
    timestamp,symbol,tf,o,h,l,c,v,spread
    2024-01-01T09:00:00Z,USDJPY,5m,150.10,150.20,150.00,150.12,,
    2024-01-01T09:05:00Z,USDJPY,5m,150.11,150.21,150.01,150.13,0.0,0.01
    """
)


class TestRunSimCLI(unittest.TestCase):
    def test_load_bars_csv(self):
        path = os.path.join(os.path.dirname(__file__), "_tmp_bars.csv")
        with open(path, "w") as f:
            f.write(CSV_CONTENT)
        try:
            bars_iter = load_bars_csv(path)
            self.assertIs(iter(bars_iter), bars_iter)
            bars = list(bars_iter)
            self.assertGreaterEqual(len(bars), 7)
            self.assertEqual(bars[0]["tf"], "5m")
            self.assertEqual(bars[0]["symbol"], "USDJPY")
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    def test_load_bars_csv_tolerates_blank_volume_and_spread(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "bars.csv"
            csv_path.write_text(CSV_CONTENT_WITH_BLANK_SPREAD, encoding="utf-8")
            bars = list(load_bars_csv(str(csv_path)))

        self.assertEqual(len(bars), 2)
        self.assertEqual(bars[0]["v"], 0.0)
        self.assertEqual(bars[0]["spread"], 0.0)
        self.assertEqual(bars[1]["v"], 0.0)
        self.assertEqual(bars[1]["spread"], 0.01)

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

    def test_run_sim_accepts_blank_volume_and_spread(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "bars.csv"
            csv_path.write_text(CSV_CONTENT_WITH_BLANK_SPREAD, encoding="utf-8")
            json_out = Path(tmpdir) / "metrics.json"

            args = [
                "--csv",
                str(csv_path),
                "--symbol",
                "USDJPY",
                "--mode",
                "conservative",
                "--equity",
                "100000",
                "--json-out",
                str(json_out),
                "--dump-max",
                "0",
                "--no-auto-state",
                "--no-ev-profile",
                "--no-aggregate-ev",
            ]

            rc = run_sim_main(args)

            self.assertEqual(rc, 0)
            self.assertTrue(json_out.exists())
            data = json.loads(json_out.read_text(encoding="utf-8"))
            self.assertIn("trades", data)

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
                captured["bars_is_iterator"] = iter(bars) is bars
                bars_list = list(bars)
                captured["bars"] = bars_list
                captured["lifecycle_type"] = type(self.lifecycle)
                captured["execution_type"] = type(self.execution)
                with mock.patch.object(
                    self.lifecycle,
                    "reset_runtime_state",
                    wraps=self.lifecycle.reset_runtime_state,
                ) as mock_reset, mock.patch.object(
                    self.lifecycle,
                    "init_ev_state",
                    wraps=self.lifecycle.init_ev_state,
                ) as mock_init, mock.patch.object(
                    self.lifecycle,
                    "reset_slip_learning",
                    wraps=self.lifecycle.reset_slip_learning,
                ) as mock_slip, mock.patch.object(
                    self.lifecycle,
                    "restore_loaded_state_snapshot",
                    wraps=self.lifecycle.restore_loaded_state_snapshot,
                ) as mock_restore:
                    result = original_run(self, bars_list, *run_args, **run_kwargs)
                captured["lifecycle_calls"] = (
                    mock_reset.call_count,
                    mock_init.call_count,
                    mock_slip.call_count,
                    mock_restore.call_count,
                )
                return result

            with mock.patch.object(backtest_runner_cls, "run", autospec=True, side_effect=_wrapped) as patched_run:
                rc = run_sim_main(args)
            self.assertEqual(rc, 0)
            patched_run.assert_called_once()
            bars_arg = captured.get("bars")
            self.assertIsNotNone(bars_arg)
            self.assertTrue(captured.get("bars_is_iterator"))
            self.assertEqual(len(bars_arg), 3)
            self.assertIs(captured.get("lifecycle_type"), RunnerLifecycleManager)
            self.assertIs(captured.get("execution_type"), RunnerExecutionManager)
            lifecycle_calls = captured.get("lifecycle_calls")
            self.assertIsNotNone(lifecycle_calls)
            self.assertTrue(all(count >= 1 for count in lifecycle_calls))
            with open(json_out, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertIn("sharpe", data)
            self.assertIn("max_drawdown", data)

    def test_run_sim_streams_bars_into_runner(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "bars.csv")
            with open(csv_path, "w", encoding="utf-8") as f:
                f.write(CSV_CONTENT)
            json_out = os.path.join(tmpdir, "metrics.json")
            args = [
                "--csv", csv_path,
                "--mode", "conservative",
                "--equity", "100000",
                "--json-out", json_out,
                "--dump-max", "0",
                "--no-auto-state",
                "--no-ev-profile",
                "--no-aggregate-ev",
            ]

            backtest_runner_cls = run_sim_main.__globals__["BacktestRunner"]
            captured = {}

            class DummyMetrics:
                def __init__(self):
                    self.records = []
                    self.daily = {}
                    self.runtime = {}
                    self.debug = {}

                def as_dict(self):
                    return {"trades": 0, "wins": 0, "total_pips": 0.0}

            def _fake_run(self, bars, *run_args, **run_kwargs):
                captured["iter_is_self"] = iter(bars) is bars
                captured["consumed"] = list(bars)
                return DummyMetrics()

            with mock.patch.object(backtest_runner_cls, "run", autospec=True, side_effect=_fake_run):
                rc = run_sim_main(args)

            self.assertEqual(rc, 0)
            consumed = captured.get("consumed")
            self.assertIsNotNone(consumed)
            self.assertTrue(captured.get("iter_is_self"))
            self.assertGreaterEqual(len(consumed), 1)
            self.assertEqual(consumed[0]["timestamp"], "2024-01-01T08:00:00Z")
            with open(json_out, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertIn("trades", data)

    def test_run_sim_auto_symbol_filters_mixed_csv(self):
        mixed_csv = textwrap.dedent(
            """\
            timestamp,symbol,tf,o,h,l,c,v,spread,zscore
            2024-01-01T08:00:00Z,USDJPY,5m,150.00,150.10,149.90,150.02,0,0.02,0.0
            2024-01-01T08:05:00Z,EURUSD,5m,1.0800,1.0810,1.0790,1.0802,0,0.01,0.1
            2024-01-01T08:10:00Z,USDJPY,5m,150.02,150.12,149.92,150.04,0,0.02,0.5
            2024-01-01T08:15:00Z,EURUSD,5m,1.0801,1.0811,1.0791,1.0803,0,0.01,-0.2
            2024-01-01T08:20:00Z,USDJPY,5m,150.04,150.14,149.94,150.06,0,0.02,-0.1
            """
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "bars.csv")
            with open(csv_path, "w", encoding="utf-8") as f:
                f.write(mixed_csv)

            json_out = os.path.join(tmpdir, "metrics.json")
            args = [
                "--csv",
                csv_path,
                "--mode",
                "conservative",
                "--equity",
                "100000",
                "--json-out",
                json_out,
                "--dump-max",
                "0",
                "--no-auto-state",
                "--no-ev-profile",
                "--no-aggregate-ev",
            ]

            backtest_runner_cls = run_sim_main.__globals__["BacktestRunner"]
            captured = {}

            class DummyMetrics:
                def __init__(self):
                    self.records = []
                    self.daily = {}
                    self.runtime = {}
                    self.debug = {}

                def as_dict(self):
                    return {"trades": 0, "wins": 0, "total_pips": 0.0}

            def _fake_run(self, bars, *run_args, **run_kwargs):
                consumed = list(bars)
                captured["symbols"] = {bar.get("symbol") for bar in consumed}
                captured["first_timestamp"] = consumed[0].get("timestamp") if consumed else None
                captured["count"] = len(consumed)
                return DummyMetrics()

            with mock.patch.object(backtest_runner_cls, "run", autospec=True, side_effect=_fake_run):
                rc = run_sim_main(args)

            self.assertEqual(rc, 0)
            self.assertEqual(captured.get("symbols"), {"USDJPY"})
            self.assertEqual(captured.get("first_timestamp"), "2024-01-01T08:00:00Z")
            self.assertGreaterEqual(captured.get("count", 0), 3)
            with open(json_out, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertIn("trades", data)

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

            def _signals_wrapper(self, ctx=None):
                intents = original_signals(self, ctx)
                ctx_snapshot = self.resolve_runtime_context(ctx)
                if intents and ctx_snapshot.get("ev_oco") is not None:
                    sig = intents[0]
                    expected = compute_qty_from_ctx(
                        ctx_snapshot,
                        sig.oco["sl_pips"],
                        mode="production",
                        tp_pips=sig.oco["tp_pips"],
                        p_lcb=ctx_snapshot["ev_oco"].p_lcb(),
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
    def test_manifest_instrument_mode_respects_cli_override(self, mock_runner):
        class DummyMetrics:
            def __init__(self):
                self.records = []
                self.runtime = {}
                self.debug = {}
                self.daily = {}

            def as_dict(self):
                return {"trades": 0, "wins": 0, "total_pips": 0.0}

        runner_instance = mock_runner.return_value
        runner_instance.strategy_cls = MeanReversionStrategy
        runner_instance.ev_global = types.SimpleNamespace(decay=0.2)
        runner_instance.run.return_value = DummyMetrics()

        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "bars.csv")
            with open(csv_path, "w", encoding="utf-8") as f:
                f.write(CSV_CONTENT)
            json_out = os.path.join(tmpdir, "metrics.json")
            manifest_yaml = textwrap.dedent(
                """
                meta:
                  id: instrument_mode_override
                  name: Instrument Mode Override
                  version: "1.0"
                  category: day
                strategy:
                  class_path: strategies.mean_reversion.MeanReversionStrategy
                  instruments:
                    - symbol: USDJPY
                      timeframe: 5m
                      mode: bridge
                  parameters:
                    or_n: 2
                router:
                  allowed_sessions: [LDN, NY]
                risk:
                  risk_per_trade_pct: 0.2
                  max_daily_dd_pct: 6.0
                  notional_cap: 300000
                  max_concurrent_positions: 1
                  warmup_trades: 0
                runner:
                  runner_config:
                    warmup_trades: 0
                state:
                  archive_namespace: strategies.mean_reversion.MeanReversionStrategy/USDJPY/bridge
                """
            )
            manifest_path = os.path.join(tmpdir, "manifest.yaml")
            with open(manifest_path, "w", encoding="utf-8") as f:
                f.write(manifest_yaml)

            args = [
                "--csv", csv_path,
                "--equity", "100000",
                "--json-out", json_out,
                "--strategy-manifest", manifest_path,
                "--mode", "conservative",
                "--no-auto-state",
                "--no-ev-profile",
                "--no-aggregate-ev",
            ]

            rc = run_sim_main(args)

        self.assertEqual(rc, 0)
        runner_instance.run.assert_called_once()
        _, run_kwargs = runner_instance.run.call_args
        self.assertEqual(run_kwargs.get("mode"), "conservative")

    @mock.patch("scripts.run_sim.BacktestRunner")
    def test_manifest_cli_args_apply_defaults(self, mock_runner):
        class DummyMetrics:
            def __init__(self):
                self.records = []
                self.runtime = {}
                self.debug = {}
                self.daily = {
                    "2024-01-01": {
                        "breakouts": 0,
                        "gate_pass": 0,
                        "gate_block": 0,
                        "ev_pass": 0,
                        "ev_reject": 0,
                        "fills": 0,
                        "wins": 0,
                        "pnl_pips": 0.0,
                    }
                }

            def as_dict(self):
                return {"trades": 0, "wins": 0, "total_pips": 0.0}

        runner_instance = mock_runner.return_value
        runner_instance.strategy_cls = MeanReversionStrategy
        runner_instance.ev_global = types.SimpleNamespace(decay=0.15)
        runner_instance.run.return_value = DummyMetrics()

        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "bars.csv")
            with open(csv_path, "w", encoding="utf-8") as f:
                f.write(CSV_CONTENT)
            json_out = os.path.join(tmpdir, "metrics.json")
            dump_daily_path = os.path.join(tmpdir, "daily.csv")
            manifest_yaml = textwrap.dedent(
                f"""
                meta:
                  id: defaults_test
                  name: Defaults Test
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
                router:
                  allowed_sessions: [LDN, NY]
                risk:
                  risk_per_trade_pct: 0.1
                  max_daily_dd_pct: 5.0
                  notional_cap: 250000
                  max_concurrent_positions: 1
                  warmup_trades: 0
                runner:
                  cli_args:
                    dump_daily: {json.dumps(dump_daily_path)}
                    mode: bridge
                    dump_max: 42
                    include_expected_slip: true
                    allowed_sessions: "LDN,NY"
                state:
                  archive_namespace: defaults/test
                """
            )
            manifest_path = os.path.join(tmpdir, "manifest.yaml")
            with open(manifest_path, "w", encoding="utf-8") as f:
                f.write(manifest_yaml)

            args = [
                "--csv", csv_path,
                "--equity", "100000",
                "--json-out", json_out,
                "--strategy-manifest", manifest_path,
                "--no-auto-state",
                "--no-ev-profile",
                "--no-aggregate-ev",
            ]

            rc = run_sim_main(args)

            self.assertEqual(rc, 0)
            runner_instance.run.assert_called_once()
            _, run_kwargs = runner_instance.run.call_args
            self.assertEqual(run_kwargs.get("mode"), "bridge")

            call_args = mock_runner.call_args
            self.assertIsNotNone(call_args)
            rcfg = call_args.kwargs.get("runner_cfg")
            self.assertIsInstance(rcfg, RunnerConfig)
            self.assertEqual(rcfg.allowed_sessions, ("LDN", "NY"))
            self.assertTrue(rcfg.include_expected_slip)

            with open(json_out, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(data.get("dump_daily"), dump_daily_path)
            self.assertTrue(os.path.exists(dump_daily_path))

    @mock.patch("scripts.run_sim.BacktestRunner")
    def test_manifest_cli_args_respect_user_overrides(self, mock_runner):
        class DummyMetrics:
            def __init__(self):
                self.records = []
                self.runtime = {}
                self.debug = {}
                self.daily = {
                    "2024-01-02": {
                        "breakouts": 0,
                        "gate_pass": 0,
                        "gate_block": 0,
                        "ev_pass": 0,
                        "ev_reject": 0,
                        "fills": 0,
                        "wins": 0,
                        "pnl_pips": 0.0,
                    }
                }

            def as_dict(self):
                return {"trades": 0, "wins": 0, "total_pips": 0.0}

        runner_instance = mock_runner.return_value
        runner_instance.strategy_cls = MeanReversionStrategy
        runner_instance.ev_global = types.SimpleNamespace(decay=0.25)
        runner_instance.run.return_value = DummyMetrics()

        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "bars.csv")
            with open(csv_path, "w", encoding="utf-8") as f:
                f.write(CSV_CONTENT)
            json_out = os.path.join(tmpdir, "metrics.json")
            user_dump_daily = os.path.join(tmpdir, "user_daily.csv")
            manifest_yaml = textwrap.dedent(
                """
                meta:
                  id: defaults_override
                  name: Defaults Override
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
                router:
                  allowed_sessions: [LDN, NY]
                risk:
                  risk_per_trade_pct: 0.2
                  max_daily_dd_pct: 6.0
                  notional_cap: 300000
                  max_concurrent_positions: 1
                  warmup_trades: 0
                runner:
                  cli_args:
                    dump_daily: manifest_daily.csv
                    mode: bridge
                state:
                  archive_namespace: defaults/override
                """
            )
            manifest_path = os.path.join(tmpdir, "manifest.yaml")
            with open(manifest_path, "w", encoding="utf-8") as f:
                f.write(manifest_yaml)

            args = [
                "--csv", csv_path,
                "--equity", "100000",
                "--json-out", json_out,
                "--strategy-manifest", manifest_path,
                "--dump-daily", user_dump_daily,
                "--mode", "conservative",
                "--no-auto-state",
                "--no-ev-profile",
                "--no-aggregate-ev",
            ]

            rc = run_sim_main(args)

            self.assertEqual(rc, 0)
            runner_instance.run.assert_called_once()
            _, run_kwargs = runner_instance.run.call_args
            self.assertEqual(run_kwargs.get("mode"), "conservative")

            with open(json_out, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(data.get("dump_daily"), user_dump_daily)
            self.assertTrue(os.path.exists(user_dump_daily))

    @mock.patch("scripts.run_sim.BacktestRunner")
    def test_manifest_no_ev_profile_skips_aggregate_out_yaml(self, mock_runner):
        class DummyMetrics:
            def __init__(self):
                self.records = []
                self.runtime = {}
                self.debug = {}
                self.daily = {}

            def as_dict(self):
                return {"trades": 0, "wins": 0, "total_pips": 0.0}

        runner_instance = mock_runner.return_value
        runner_instance.strategy_cls = MeanReversionStrategy
        runner_instance.ev_global = types.SimpleNamespace(decay=0.15)
        runner_instance.run.return_value = DummyMetrics()
        runner_instance.export_state.return_value = {"state": "ok"}

        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "bars.csv"
            csv_path.write_text(CSV_CONTENT, encoding="utf-8")
            json_out = Path(tmpdir) / "metrics.json"
            ev_profile_path = Path(tmpdir) / "profile.yaml"
            ev_profile_path.write_text("{}", encoding="utf-8")
            archive_root = Path(tmpdir) / "state_archive"
            manifest_yaml = textwrap.dedent(
                f"""
                meta:
                  id: manifest_ev_profile_skip
                  name: Manifest EV Profile Skip
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
                router:
                  allowed_sessions: [LDN]
                risk:
                  risk_per_trade_pct: 0.2
                  max_daily_dd_pct: 6.0
                  notional_cap: 300000
                  max_concurrent_positions: 1
                  warmup_trades: 0
                runner:
                  runner_config:
                    warmup_trades: 0
                state:
                  archive_namespace: strategies.mean_reversion.MeanReversionStrategy/USDJPY/conservative
                  ev_profile: {ev_profile_path}
                """
            )
            manifest_path = Path(tmpdir) / "manifest.yaml"
            manifest_path.write_text(manifest_yaml, encoding="utf-8")

            args = [
                "--csv",
                str(csv_path),
                "--equity",
                "100000",
                "--json-out",
                str(json_out),
                "--strategy-manifest",
                str(manifest_path),
                "--state-archive",
                str(archive_root),
                "--no-ev-profile",
            ]

            with mock.patch("scripts.run_sim.subprocess.run") as mock_run:
                mock_run.return_value = types.SimpleNamespace(returncode=0, stdout="", stderr="")
                rc = run_sim_main(args)

        self.assertEqual(rc, 0)
        mock_runner.return_value.run.assert_called_once()
        mock_runner.return_value.export_state.assert_called()
        mock_run.assert_called_once()
        cmd_args = mock_run.call_args[0][0]
        self.assertIsInstance(cmd_args, list)
        self.assertNotIn("--out-yaml", cmd_args)
        self.assertIn("--skip-yaml", cmd_args)

    @mock.patch("scripts.run_sim.BacktestRunner")
    def test_cli_no_ev_profile_flag_blocks_aggregate_out_yaml(self, mock_runner):
        class DummyMetrics:
            def __init__(self):
                self.records = []
                self.runtime = {}
                self.debug = {}
                self.daily = {}

            def as_dict(self):
                return {"trades": 0, "wins": 0, "total_pips": 0.0}

        runner_instance = mock_runner.return_value
        runner_instance.strategy_cls = MeanReversionStrategy
        runner_instance.ev_global = types.SimpleNamespace(decay=0.1)
        runner_instance.run.return_value = DummyMetrics()
        runner_instance.export_state.return_value = {"state": "ok"}

        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "bars.csv"
            csv_path.write_text(CSV_CONTENT, encoding="utf-8")
            json_out = Path(tmpdir) / "metrics.json"
            ev_profile_path = Path(tmpdir) / "user_profile.yaml"
            archive_root = Path(tmpdir) / "archive"

            args = [
                "--csv",
                str(csv_path),
                "--equity",
                "100000",
                "--json-out",
                str(json_out),
                "--state-archive",
                str(archive_root),
                "--ev-profile",
                str(ev_profile_path),
                "--no-ev-profile",
            ]

            with mock.patch("scripts.run_sim.subprocess.run") as mock_run:
                mock_run.return_value = types.SimpleNamespace(returncode=0, stdout="", stderr="")
                rc = run_sim_main(args)

        self.assertEqual(rc, 0)
        mock_runner.return_value.run.assert_called_once()
        mock_runner.return_value.export_state.assert_called()
        mock_run.assert_called_once()
        cmd_args = mock_run.call_args[0][0]
        self.assertIsInstance(cmd_args, list)
        self.assertNotIn("--out-yaml", cmd_args)
        self.assertIn("--out-csv", cmd_args)
        self.assertIn("--skip-yaml", cmd_args)

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

    @mock.patch("scripts.run_sim.subprocess.run")
    @mock.patch("scripts.run_sim.BacktestRunner")
    @mock.patch("scripts.run_sim.utcnow_aware")
    def test_run_sim_aggregate_uses_resolved_archive_from_temp_cwd(self, mock_utcnow, mock_runner, mock_subproc):
        class DummyMetrics:
            def __init__(self):
                self.records = []
                self.daily = {}
                self.runtime = {}
                self.debug = {}

            def as_dict(self):
                return {"trades": 1, "wins": 1, "total_pips": 0.0, "sharpe": 0.0, "max_drawdown": 0.0}

        mock_utcnow.return_value = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        runner_instance = mock_runner.return_value
        runner_instance.strategy_cls = MeanReversionStrategy
        runner_instance.ev_global = types.SimpleNamespace(decay=0.25)
        runner_instance.run.return_value = DummyMetrics()
        runner_instance.export_state.return_value = {"ev_buckets": {}, "ev_global": {}}

        captured = {}

        def _mock_run(cmd, *args, **kwargs):
            captured["cmd"] = cmd
            archive_idx = cmd.index("--archive") + 1
            archive_path = Path(cmd[archive_idx])
            captured["archive_path"] = archive_path
            captured["archive_exists"] = archive_path.exists()
            captured["archive_is_absolute"] = archive_path.is_absolute()
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        mock_subproc.side_effect = _mock_run

        with tempfile.TemporaryDirectory() as data_dir, tempfile.TemporaryDirectory() as work_dir:
            csv_path = os.path.join(data_dir, "bars.csv")
            with open(csv_path, "w", encoding="utf-8") as f:
                f.write(CSV_CONTENT)
            json_out = os.path.join(data_dir, "metrics.json")
            args = [
                "--csv", csv_path,
                "--symbol", "USDJPY",
                "--mode", "conservative",
                "--equity", "100000",
                "--json-out", json_out,
                "--no-ev-profile",
                "--strategy", "strategies.mean_reversion.MeanReversionStrategy",
            ]

            original_cwd = os.getcwd()
            expected_base = Path(run_sim_main.__globals__["ROOT"]).resolve() / "ops" / "state_archive"
            timestamp = mock_utcnow.return_value.strftime("%Y%m%d_%H%M%S")
            archive_file = expected_base / "mean_reversion.MeanReversionStrategy" / "USDJPY" / "conservative" / f"{timestamp}.json"

            try:
                os.chdir(work_dir)
                rc = run_sim_main(args)
            finally:
                os.chdir(original_cwd)

            self.assertEqual(rc, 0)
            mock_subproc.assert_called()
            cmd = captured.get("cmd")
            self.assertIsNotNone(cmd)
            archive_path = captured.get("archive_path")
            self.assertIsNotNone(archive_path)
            self.assertTrue(captured.get("archive_is_absolute"))
            self.assertEqual(archive_path.resolve(), expected_base)
            self.assertTrue(captured.get("archive_exists"))

            if archive_file.exists():
                archive_file.unlink()
                current = archive_file.parent
                stop_dir = expected_base
                while stop_dir in current.parents:
                    try:
                        current.rmdir()
                    except OSError:
                        break
                    current = current.parent

    @mock.patch("scripts.run_sim.subprocess.run")
    @mock.patch("scripts.run_sim.BacktestRunner")
    def test_run_sim_manifest_triggers_aggregate_with_namespace(self, mock_runner, mock_subproc):
        class DummyMetrics:
            def __init__(self):
                self.records = []
                self.daily = {}
                self.runtime = {}
                self.debug = {}

            def as_dict(self):
                return {"trades": 1, "wins": 1, "total_pips": 1.0, "sharpe": 0.0, "max_drawdown": 0.0}

        mock_subproc.return_value = types.SimpleNamespace(returncode=0, stdout="", stderr="")
        runner_instance = mock_runner.return_value
        runner_instance.strategy_cls = MeanReversionStrategy
        runner_instance.ev_global = types.SimpleNamespace(decay=0.5)
        runner_instance.run.return_value = DummyMetrics()
        runner_instance.export_state.return_value = {"ev_buckets": {}, "ev_global": {}}

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
                zscore_threshold: 1.0
                allow_high_rv: true
            router:
              allowed_sessions: [LDN]
            risk:
              risk_per_trade_pct: 0.1
              max_concurrent_positions: 1
              warmup_trades: 0
            runner:
              runner_config:
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
            state_archive = os.path.join(tmpdir, "state_archive")
            args = [
                "--csv", csv_path,
                "--equity", "100000",
                "--strategy-manifest", manifest_path,
                "--state-archive", state_archive,
                "--dump-max", "0",
                "--json-out", os.path.join(tmpdir, "out.json"),
            ]

            rc = run_sim_main(args)

        self.assertEqual(rc, 0)
        mock_subproc.assert_called()
        called_args = mock_subproc.call_args[0][0]
        self.assertIn("--archive-namespace", called_args)
        namespace_index = called_args.index("--archive-namespace") + 1
        self.assertIn(
            "strategies.mean_reversion.MeanReversionStrategy/USDJPY/conservative",
            called_args[namespace_index],
        )


if __name__ == "__main__":
    unittest.main()
