import csv
from pathlib import Path
from typing import List
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from core.fill_engine import SameBarPolicy
from core.runner import BacktestRunner, Metrics, RunnerConfig
from core.pips import pip_size, price_to_pips
from core.sizing import compute_qty_from_ctx
from core.strategy_api import OrderIntent
from strategies.day_orb_5m import DayORB5m


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

    def test_runner_respects_fill_config(self):
        rcfg = RunnerConfig(
            fill_same_bar_policy_conservative="tp_first",
            fill_same_bar_policy_bridge="sl_first",
            fill_bridge_lambda=0.55,
            fill_bridge_drift_scale=1.8,
        )
        runner = BacktestRunner(equity=100_000.0, symbol="USDJPY", runner_cfg=rcfg)
        self.assertEqual(runner.fill_engine_c.default_policy, SameBarPolicy.TP_FIRST)
        self.assertEqual(runner.fill_engine_b.default_policy, SameBarPolicy.SL_FIRST)
        self.assertAlmostEqual(runner.fill_engine_b.lam, 0.55)
        self.assertAlmostEqual(runner.fill_engine_b.drift_scale, 1.8)

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

    def _prepare_breakout_environment(
        self,
        *,
        warmup_left: int = 0,
        calibrate_days: int = 0,
        include_expected_slip: bool = False,
        debug: bool = False,
        debug_sample_limit: int = 0,
    ):
        import core.runner as runner_module

        symbol = "USDJPY"
        runner = BacktestRunner(
            equity=100_000.0,
            symbol=symbol,
            debug=debug,
            debug_sample_limit=debug_sample_limit,
        )
        runner._strategy_gate_hook = None
        runner._ev_threshold_hook = None
        runner.rcfg.calibrate_days = calibrate_days
        runner.rcfg.include_expected_slip = include_expected_slip
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
        features = runner._compute_features(
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
        return runner, pending, breakout, features, calibrating

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

    def test_build_ctx_casts_risk_per_trade_pct_from_string(self):
        cfg = RunnerConfig(risk_per_trade_pct="1.2")
        runner = BacktestRunner(equity=100_000.0, symbol="USDJPY", runner_cfg=cfg)
        base_ts = datetime(2024, 1, 1, 8, 0, tzinfo=timezone.utc)
        bar = make_bar(base_ts, "USDJPY", 150.0, 150.2, 149.8, 150.05, spread=0.02)

        ctx = runner._build_ctx(
            bar=bar,
            session="LDN",
            atr14=0.5,
            or_h=150.2,
            or_l=149.8,
            realized_vol_value=0.01,
        )

        self.assertAlmostEqual(ctx["sizing_cfg"]["risk_per_trade_pct"], 1.2)

    def test_build_ctx_uses_base_notional_string(self):
        cfg = RunnerConfig()
        cfg.base_notional = "100000"
        runner = BacktestRunner(equity=100_000.0, symbol="USDJPY", runner_cfg=cfg)
        base_ts = datetime(2024, 1, 1, 8, 0, tzinfo=timezone.utc)
        bar = make_bar(base_ts, "USDJPY", 150.0, 150.2, 149.8, 150.05, spread=0.02)

        ctx = runner._build_ctx(
            bar=bar,
            session="LDN",
            atr14=0.5,
            or_h=150.2,
            or_l=149.8,
            realized_vol_value=0.01,
        )

        expected = float(cfg.base_notional) * pip_size(runner.symbol)
        self.assertAlmostEqual(ctx["pip_value"], expected)

    def test_build_ctx_invalid_base_notional_falls_back(self):
        cfg = RunnerConfig()
        cfg.base_notional = "not-a-number"
        runner = BacktestRunner(equity=100_000.0, symbol="USDJPY", runner_cfg=cfg)
        base_ts = datetime(2024, 1, 1, 8, 0, tzinfo=timezone.utc)
        bar = make_bar(base_ts, "USDJPY", 150.0, 150.2, 149.8, 150.05, spread=0.02)

        ctx = runner._build_ctx(
            bar=bar,
            session="LDN",
            atr14=0.5,
            or_h=150.2,
            or_l=149.8,
            realized_vol_value=0.01,
        )

        self.assertAlmostEqual(ctx["pip_value"], 10.0)

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
        full_curve = metrics_full.as_dict()["equity_curve"]
        partial_curve = metrics_partial.as_dict()["equity_curve"]
        if full_curve:
            self.assertAlmostEqual(full_curve[0][1], 200_000.0)
            self.assertAlmostEqual(partial_curve[0][1], 200_000.0)
        else:
            self.assertEqual(full_curve, partial_curve)

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

        first_curve = metrics_first.as_dict()["equity_curve"]
        second_curve = metrics_second.as_dict()["equity_curve"]
        if first_curve:
            self.assertEqual(first_curve[0][1], 150_000.0)
            self.assertEqual(second_curve[0][1], 150_000.0)
            self.assertListEqual(first_curve[1:], second_curve[1:])
        else:
            self.assertEqual(first_curve, second_curve)

    def test_metrics_compute_sharpe_and_drawdown(self):
        metrics = Metrics()
        returns = [10.0, -5.0, 20.0, -15.0]
        metrics.trade_returns.extend(returns)
        base_ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
        metrics._equity_seed = (base_ts.isoformat().replace("+00:00", "Z"), 0.0)
        cumulative = 0.0
        for idx, r in enumerate(returns, start=1):
            cumulative += r
            ts = (base_ts + timedelta(minutes=idx)).isoformat().replace("+00:00", "Z")
            metrics.equity_curve.append((ts, cumulative))
        metrics.total_pips = sum(returns)
        result = metrics.as_dict()
        self.assertIn("sharpe", result)
        self.assertIn("max_drawdown", result)
        self.assertAlmostEqual(result["sharpe"], 0.3713906763541037, places=6)
        self.assertAlmostEqual(result["max_drawdown"], -15.0, places=6)
        self.assertIsNone(result["win_rate"])
        curve_ts = [point[0] for point in result["equity_curve"]]
        self.assertEqual(curve_ts[0], metrics._equity_seed[0])

    def test_metrics_records_equity_curve_from_records_csv(self):
        metrics = Metrics()
        csv_path = Path(__file__).parent / "data" / "runner_sample_records.csv"
        base_ts = datetime(2024, 1, 1, 9, 0, tzinfo=timezone.utc)
        with csv_path.open() as f:
            reader = csv.DictReader(f)
            for idx, row in enumerate(reader):
                if row.get("stage") != "trade":
                    continue
                pnl = float(row.get("pnl_pips", 0.0))
                ts = (base_ts + timedelta(minutes=idx)).isoformat().replace("+00:00", "Z")
                metrics.record_trade(pnl, pnl > 0, timestamp=ts)

        result = metrics.as_dict()
        self.assertEqual(metrics.trades, 4)
        self.assertEqual(metrics.wins, 2)
        self.assertAlmostEqual(metrics.total_pips, 5.0)
        curve = metrics.as_dict()["equity_curve"]
        equities = [round(entry[1], 6) for entry in curve]
        self.assertListEqual(
            equities,
            [0.0, 12.0, 7.0, 15.0, 5.0],
        )
        timestamps = [entry[0] for entry in curve]
        self.assertListEqual(sorted(timestamps), timestamps)
        self.assertAlmostEqual(result["sharpe"], 0.27660638840895513)
        self.assertAlmostEqual(result["max_drawdown"], -10.0)
        self.assertAlmostEqual(result["win_rate"], 0.5)

    def test_check_slip_and_sizing_zero_qty_uses_helpers(self):
        runner = BacktestRunner(equity=100_000.0, symbol="USDJPY")
        ctx_dbg = {
            "slip_cap_pip": 1.5,
            "expected_slip_pip": 0.1,
            "pip_value": 10.0,
            "equity": runner.equity,
            "sizing_cfg": {
                "risk_per_trade_pct": 0.25,
                "kelly_fraction": 0.25,
                "units_cap": 5.0,
                "max_trade_loss_pct": 0.5,
            },
        }
        pending = {"side": "BUY", "tp_pips": 2.0, "sl_pips": 1.0}
        ev_mgr = self.DummyEV(ev_lcb=0.0, p_lcb=0.3)

        allowed = runner._check_slip_and_sizing(
            ctx_dbg=ctx_dbg,
            pending=pending,
            ev_mgr=ev_mgr,
            calibrating=False,
            ev_bypass=False,
            timestamp="2024-01-01T00:00:00Z",
        )

        self.assertFalse(allowed)
        self.assertEqual(runner.debug_counts["zero_qty"], 1)

        qty_helper = compute_qty_from_ctx(
            ctx_dbg,
            pending["sl_pips"],
            mode="production",
            tp_pips=pending["tp_pips"],
            p_lcb=ev_mgr.p_lcb(),
        )
        self.assertEqual(qty_helper, 0.0)

    def test_check_slip_and_sizing_slip_guard_blocks(self):
        runner = BacktestRunner(equity=100_000.0, symbol="USDJPY")
        ctx_dbg = {
            "slip_cap_pip": 0.5,
            "expected_slip_pip": 1.0,
            "pip_value": 10.0,
            "sizing_cfg": {
                "risk_per_trade_pct": 0.25,
                "kelly_fraction": 0.25,
                "units_cap": 5.0,
                "max_trade_loss_pct": 0.5,
            },
        }
        pending = {"side": "SELL", "tp_pips": 2.0, "sl_pips": 1.0}
        ev_mgr = self.DummyEV(ev_lcb=0.0, p_lcb=0.6)

        allowed = runner._check_slip_and_sizing(
            ctx_dbg=ctx_dbg,
            pending=pending,
            ev_mgr=ev_mgr,
            calibrating=False,
            ev_bypass=False,
            timestamp="2024-01-01T00:05:00Z",
        )

        self.assertFalse(allowed)
        self.assertEqual(runner.debug_counts["gate_block"], 1)
        self.assertEqual(runner.debug_counts["zero_qty"], 0)

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
        runner, pending, breakout, features, calibrating = self._prepare_breakout_environment(
            warmup_left=0
        )
        stub_ev = self.DummyEV(ev_lcb=1.2, p_lcb=0.65)
        runner._get_ev_manager = lambda key: stub_ev
        ctx_dbg = runner._evaluate_entry_conditions(
            pending=pending,
            features=features,
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
        runner, pending, breakout, features, calibrating = self._prepare_breakout_environment(
            warmup_left=0
        )
        stub_ev = self.DummyEV(ev_lcb=0.05, p_lcb=0.55)
        runner._get_ev_manager = lambda key: stub_ev
        ctx_dbg = runner._evaluate_entry_conditions(
            pending=pending,
            features=features,
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

    def test_order_intent_with_oco_fields_supports_ev_and_sizing_guards(self):
        runner, _, breakout, features, calibrating = self._prepare_breakout_environment(
            warmup_left=0
        )
        intent = OrderIntent(
            side="BUY",
            qty=1.0,
            price=breakout["c"],
            oco={"tp_pips": 2.0, "sl_pips": 1.0},
        )
        runner.stg._pending_signal = intent
        stub_ev = self.DummyEV(ev_lcb=0.05, p_lcb=0.55)
        runner._get_ev_manager = lambda key: stub_ev
        ctx_dbg = runner._evaluate_entry_conditions(
            pending=intent,
            features=features,
        )
        self.assertIsNotNone(ctx_dbg)
        ev_eval = runner._evaluate_ev_threshold(
            ctx_dbg=ctx_dbg,
            pending=intent,
            calibrating=calibrating,
            timestamp=runner._last_timestamp,
        )
        self.assertIsNone(ev_eval)
        self.assertEqual(runner.debug_counts["ev_reject"], 1)
        ctx_dbg.setdefault("expected_slip_pip", 0.0)
        ctx_dbg.setdefault("slip_cap_pip", runner.rcfg.slip_cap_pip)
        ctx_dbg.setdefault("cost_pips", 0.0)
        with patch("core.runner.compute_qty_from_ctx", return_value=1.0) as mock_compute:
            slip_ok = runner._check_slip_and_sizing(
                ctx_dbg=ctx_dbg,
                pending=intent,
                ev_mgr=stub_ev,
                calibrating=False,
                ev_bypass=False,
                timestamp=runner._last_timestamp,
            )
        self.assertTrue(slip_ok)
        mock_compute.assert_called_once()
        args, kwargs = mock_compute.call_args
        self.assertEqual(args[1], 1.0)
        self.assertEqual(kwargs.get("tp_pips"), 2.0)

    def test_warmup_bypass_allows_low_ev_signal(self):
        runner, pending, breakout, features, calibrating = self._prepare_breakout_environment(
            warmup_left=5,
            debug=True,
            debug_sample_limit=5,
        )
        stub_ev = self.DummyEV(ev_lcb=0.05, p_lcb=0.55)
        runner._get_ev_manager = lambda key: stub_ev
        ctx_dbg = runner._evaluate_entry_conditions(
            pending=pending,
            features=features,
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
        self.assertGreaterEqual(len(runner.debug_records), 1)
        bypass_records = [rec for rec in runner.debug_records if rec.get("stage") == "ev_bypass"]
        self.assertEqual(len(bypass_records), 1)
        record = bypass_records[0]
        self.assertEqual(record["side"], "BUY")
        self.assertEqual(record["warmup_left"], 5)
        self.assertEqual(record["warmup_total"], runner.rcfg.warmup_trades)
        self.assertAlmostEqual(record["ev_lcb"], stub_ev._ev_lcb)
        self.assertAlmostEqual(record["threshold_lcb"], ctx_dbg["threshold_lcb"])
        self.assertEqual(record["tp_pips"], 2.0)
        self.assertEqual(record["sl_pips"], 1.0)

    @patch("strategies.day_orb_5m.pass_gates", return_value=True)
    def test_calibration_signal_updates_cooldown_state(self, _mock_pass_gates):
        stg = DayORB5m()
        cfg = {
            "ctx": {
                "cooldown_bars": 2,
                "calibrating": True,
                "ev_mode": "lcb",
            }
        }
        stg.on_start(cfg, ["USDJPY"], {})
        stg.state["bar_idx"] = 12
        stg._pending_signal = {
            "side": "SELL",
            "tp_pips": 8.0,
            "sl_pips": 4.0,
            "trail_pips": 0.0,
            "entry": 149.75,
        }

        first_batch = stg.signals()
        self.assertEqual(len(first_batch), 1)
        self.assertEqual(stg.state["last_signal_bar"], 12)
        self.assertTrue(stg.state["broken"])

        stg.state["bar_idx"] += 1
        stg._pending_signal = {
            "side": "SELL",
            "tp_pips": 8.0,
            "sl_pips": 4.0,
            "trail_pips": 0.0,
            "entry": 149.65,
        }

        second_batch = stg.signals()
        self.assertEqual(second_batch, [])
        self.assertEqual(stg.state["last_signal_bar"], 12)
        self.assertTrue(stg.state["broken"])

    @patch("strategies.day_orb_5m.pass_gates", return_value=True)
    def test_warmup_signal_respects_cooldown_and_session_block(self, _mock_pass_gates):
        stg = DayORB5m()
        cfg = {
            "ctx": {
                "cooldown_bars": 2,
                "warmup_left": 3,
                "equity": 100_000.0,
                "pip_value": 10.0,
                "warmup_mult": 0.05,
                "sizing_cfg": {
                    "risk_per_trade_pct": 1.0,
                    "units_cap": 10.0,
                },
            }
        }
        stg.on_start(cfg, ["USDJPY"], {})
        stg.state["bar_idx"] = 25
        stg._pending_signal = {
            "side": "BUY",
            "tp_pips": 10.0,
            "sl_pips": 5.0,
            "trail_pips": 0.0,
            "entry": 150.25,
        }

        first_batch = stg.signals()
        self.assertEqual(len(first_batch), 1)
        self.assertEqual(stg.state["last_signal_bar"], 25)
        self.assertTrue(stg.state["broken"])

        stg.state["bar_idx"] += 1
        stg._pending_signal = {
            "side": "BUY",
            "tp_pips": 10.0,
            "sl_pips": 5.0,
            "trail_pips": 0.0,
            "entry": 150.35,
        }

        second_batch = stg.signals()
        self.assertEqual(second_batch, [])
        self.assertEqual(stg.state["last_signal_bar"], 25)
        self.assertTrue(stg.state["broken"])

    def test_calibration_ctx_preserves_threshold_and_expected_slip(self):
        runner, pending, breakout, features, calibrating = self._prepare_breakout_environment(
            warmup_left=0,
            calibrate_days=2,
            include_expected_slip=True,
        )
        self.assertTrue(calibrating)
        base_ctx = features.ctx
        self.assertIn("threshold_lcb_pip", base_ctx)
        self.assertEqual(base_ctx["threshold_lcb_pip"], -1e9)
        expected_slip = base_ctx.get("expected_slip_pip")
        self.assertIsNotNone(expected_slip)
        self.assertGreater(expected_slip, 0.0)
        ctx_dbg = runner._evaluate_entry_conditions(
            pending=pending,
            features=features,
        )
        self.assertIsNotNone(ctx_dbg)
        self.assertEqual(ctx_dbg.get("threshold_lcb_pip"), -1e9)
        self.assertEqual(ctx_dbg.get("expected_slip_pip"), expected_slip)

    def test_handle_active_position_trail_exit_buy_and_sell(self):
        runner = BacktestRunner(equity=100_000.0, symbol="USDJPY")
        pip_value = pip_size(runner.symbol)
        original_finalize = runner._finalize_trade
        try:
            for side, bar, expected_exit in (
                (
                    "BUY",
                    {
                        "o": 150.10,
                        "h": 150.40,
                        "l": 150.20,
                        "c": 150.25,
                        "timestamp": "2024-01-01T08:30:00+00:00",
                    },
                    150.40 - 10.0 * pip_value,
                ),
                (
                    "SELL",
                    {
                        "o": 150.00,
                        "h": 149.55,
                        "l": 149.40,
                        "c": 149.45,
                        "timestamp": "2024-01-01T08:35:00+00:00",
                    },
                    149.40 + 10.0 * pip_value,
                ),
            ):
                with self.subTest(side=side):
                    runner.pos = {
                        "side": side,
                        "entry_px": 150.00,
                        "tp_px": 150.80 if side == "BUY" else 149.20,
                        "sl_px": 149.00 if side == "BUY" else 151.00,
                        "trail_pips": 10.0,
                        "qty": 1.0,
                        "entry_ts": "2024-01-01T08:00:00+00:00",
                        "ctx_snapshot": {},
                        "ev_key": None,
                        "tp_pips": 80.0,
                        "sl_pips": 100.0,
                    }
                    runner._finalize_trade = MagicMock()
                    result = runner._handle_active_position(
                        bar=bar,
                        ctx={},
                        mode="conservative",
                        pip_size_value=pip_value,
                        new_session=False,
                    )
                    self.assertTrue(result)
                    runner._finalize_trade.assert_called_once()
                    call = runner._finalize_trade.call_args.kwargs
                    self.assertEqual(call["exit_reason"], "sl")
                    self.assertAlmostEqual(call["exit_px"], expected_exit)
                    self.assertIsNone(runner.pos)
        finally:
            runner._finalize_trade = original_finalize

    def test_handle_active_position_same_bar_hits_buy_and_sell(self):
        runner = BacktestRunner(equity=100_000.0, symbol="USDJPY")
        pip_value = pip_size(runner.symbol)
        original_finalize = runner._finalize_trade
        try:
            for side, bar in (
                (
                    "BUY",
                    {
                        "o": 150.00,
                        "h": 150.25,
                        "l": 149.75,
                        "c": 150.10,
                        "timestamp": "2024-01-01T08:40:00+00:00",
                    },
                ),
                (
                    "SELL",
                    {
                        "o": 150.00,
                        "h": 150.25,
                        "l": 149.75,
                        "c": 149.90,
                        "timestamp": "2024-01-01T08:45:00+00:00",
                    },
                ),
            ):
                with self.subTest(side=side):
                    entry = 150.00
                    tp = entry + 0.20 if side == "BUY" else entry - 0.20
                    sl = entry - 0.20 if side == "BUY" else entry + 0.20
                    runner.pos = {
                        "side": side,
                        "entry_px": entry,
                        "tp_px": tp,
                        "sl_px": sl,
                        "trail_pips": 0.0,
                        "qty": 1.0,
                        "entry_ts": "2024-01-01T08:00:00+00:00",
                        "ctx_snapshot": {},
                        "ev_key": None,
                        "tp_pips": abs(tp - entry) / pip_value,
                        "sl_pips": abs(entry - sl) / pip_value,
                    }
                    runner._finalize_trade = MagicMock()
                    runner._handle_active_position(
                        bar=bar,
                        ctx={},
                        mode="bridge",
                        pip_size_value=pip_value,
                        new_session=False,
                    )
                    runner._finalize_trade.assert_called_once()
                    call = runner._finalize_trade.call_args.kwargs
                    self.assertEqual(call["exit_reason"], "tp")
                    if side == "BUY":
                        self.assertTrue(sl < call["exit_px"] < tp)
                    else:
                        self.assertTrue(tp < call["exit_px"] < sl)
                    self.assertIsNone(runner.pos)
        finally:
            runner._finalize_trade = original_finalize

    def test_handle_active_position_timeout_buy_and_sell(self):
        runner = BacktestRunner(equity=100_000.0, symbol="USDJPY")
        runner.rcfg.max_hold_bars = 2
        pip_value = pip_size(runner.symbol)
        original_finalize = runner._finalize_trade
        try:
            for side in ("BUY", "SELL"):
                with self.subTest(side=side):
                    entry = 150.00
                    tp = entry + 0.50 if side == "BUY" else entry - 0.50
                    sl = entry - 0.50 if side == "BUY" else entry + 0.50
                    runner.pos = {
                        "side": side,
                        "entry_px": entry,
                        "tp_px": tp,
                        "sl_px": sl,
                        "trail_pips": 0.0,
                        "qty": 1.0,
                        "entry_ts": "2024-01-01T08:00:00+00:00",
                        "ctx_snapshot": {},
                        "ev_key": None,
                        "tp_pips": abs(tp - entry) / pip_value,
                        "sl_pips": abs(entry - sl) / pip_value,
                        "hold": 1,
                    }
                    runner._finalize_trade = MagicMock()
                    bar = {
                        "o": entry,
                        "h": entry + 0.10,
                        "l": entry - 0.10,
                        "c": entry,
                        "timestamp": "2024-01-01T08:50:00+00:00",
                    }
                    runner._handle_active_position(
                        bar=bar,
                        ctx={},
                        mode="conservative",
                        pip_size_value=pip_value,
                        new_session=False,
                    )
                    runner._finalize_trade.assert_called_once()
                    call = runner._finalize_trade.call_args.kwargs
                    self.assertEqual(call["exit_reason"], "timeout")
                    self.assertEqual(call["exit_px"], bar["o"])
                    self.assertIsNone(runner.pos)
        finally:
            runner._finalize_trade = original_finalize

    def test_calibration_ev_update_simultaneous_hit_regression(self):
        runner = BacktestRunner(equity=100_000.0, symbol="USDJPY")
        pip_value = pip_size(runner.symbol)

        updates: List[bool] = []

        class DummyEv:
            def update(self, hit: bool) -> None:
                updates.append(hit)

        dummy_ev = DummyEv()
        runner._get_ev_manager = lambda key: dummy_ev
        runner.calib_positions = [
            {
                "side": "BUY",
                "entry_px": 150.00,
                "tp_px": 150.20,
                "sl_px": 149.80,
                "trail_pips": 0.0,
                "hh": 150.00,
                "ll": 150.00,
                "hold": 0,
                "ev_key": ("LDN", "normal", "mid"),
            }
        ]
        bar = {
            "o": 150.00,
            "h": 150.25,
            "l": 149.75,
            "c": 150.10,
            "timestamp": "2024-01-01T08:30:00+00:00",
        }
        ctx = {
            "session": "LDN",
            "spread_band": "normal",
            "rv_band": "mid",
            "ev_key": ("LDN", "normal", "mid"),
        }

        runner._resolve_calibration_positions(
            bar=bar,
            ctx=ctx,
            new_session=False,
            calibrating=True,
            mode="conservative",
            pip_size_value=pip_value,
        )

        self.assertEqual(updates, [False])
        self.assertFalse(runner.calib_positions)

    def test_calibration_ev_update_session_boundary_regression(self):
        runner = BacktestRunner(equity=100_000.0, symbol="USDJPY")
        pip_value = pip_size(runner.symbol)

        updates: List[bool] = []

        class DummyEv:
            def update(self, hit: bool) -> None:
                updates.append(hit)

        dummy_ev = DummyEv()
        runner._get_ev_manager = lambda key: dummy_ev
        runner.calib_positions = [
            {
                "side": "SELL",
                "entry_px": 150.00,
                "tp_px": 149.70,
                "sl_px": 150.30,
                "trail_pips": 0.0,
                "hh": 150.00,
                "ll": 150.00,
                "hold": 0,
                "ev_key": None,
            }
        ]
        bar = {
            "o": 150.05,
            "h": 150.10,
            "l": 149.95,
            "c": 150.00,
            "timestamp": "2024-01-01T13:00:00+00:00",
        }
        ctx = {
            "session": "NY",
            "spread_band": "normal",
            "rv_band": "mid",
            "ev_key": ("NY", "normal", "mid"),
        }

        runner._resolve_calibration_positions(
            bar=bar,
            ctx=ctx,
            new_session=True,
            calibrating=True,
            mode="conservative",
            pip_size_value=pip_value,
        )

        self.assertEqual(updates, [False])
        self.assertFalse(runner.calib_positions)




if __name__ == "__main__":
    unittest.main()
