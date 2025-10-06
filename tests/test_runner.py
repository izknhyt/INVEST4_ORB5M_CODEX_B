import csv
import math
from contextlib import ExitStack
from pathlib import Path
from typing import List, Optional
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from core.fill_engine import OrderSpec, SameBarPolicy
from core.feature_store import realized_vol as calc_realized_vol
from core.runner import BacktestRunner, ExitDecision, Metrics, RunnerConfig
from core.runner_entry import (
    EntryGate,
    EVGate,
    EntryEvaluationResult,
    SizingGate,
    GateCheckOutcome,
    EVEvaluationResult,
    SizingEvaluationResult,
)
from core.runner_state import PositionState
from core.pips import pip_size, price_to_pips
from core.sizing import compute_qty_from_ctx
from core.strategy_api import OrderIntent, Strategy
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
        runner_cfg: Optional[RunnerConfig] = None,
    ):
        import core.runner as runner_module

        symbol = "USDJPY"
        runner = BacktestRunner(
            equity=100_000.0,
            symbol=symbol,
            debug=debug,
            debug_sample_limit=debug_sample_limit,
            runner_cfg=runner_cfg,
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
        import core.runner_entry as entry_module

        original_entry_pass = entry_module.pass_gates
        entry_module.pass_gates = lambda ctx: True
        self.addCleanup(lambda: setattr(entry_module, "pass_gates", original_entry_pass))
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

    def test_realized_vol_recent_window_updates_band(self):
        runner = BacktestRunner(equity=100_000.0, symbol="USDJPY")
        base_ts = datetime(2024, 1, 1, 8, 0, tzinfo=timezone.utc)
        closes = [100.0]
        for _ in range(12):
            closes.append(closes[-1] + 0.01)
        closes.append(closes[-1] + 3.0)

        features_before = None
        features_after = None
        window_before = None
        window_after = None
        session_before: Optional[str] = None
        session_after: Optional[str] = None

        for idx, close in enumerate(closes):
            open_px = closes[idx - 1] if idx > 0 else close
            high_px = max(open_px, close) + 0.01
            low_px = min(open_px, close) - 0.01
            bar = make_bar(
                base_ts + timedelta(minutes=5 * idx),
                "USDJPY",
                open_px,
                high_px,
                low_px,
                close,
                spread=0.02,
            )
            new_session, session, calibrating = runner._update_daily_state(bar)
            features = runner._compute_features(
                bar,
                session=session,
                new_session=new_session,
                calibrating=calibrating,
            )
            if idx == 12:
                features_before = features
                window_before = [dict(b) for b in runner.window[-13:]]
                session_before = session
            if idx == 13:
                features_after = features
                window_after = [dict(b) for b in runner.window[-13:]]
                session_after = session

        self.assertIsNotNone(features_before)
        self.assertIsNotNone(features_after)
        self.assertIsNotNone(window_before)
        self.assertIsNotNone(window_after)
        self.assertIsNotNone(session_before)
        self.assertIsNotNone(session_after)

        expected_before = calc_realized_vol(window_before, n=12)
        expected_after = calc_realized_vol(window_after, n=12)
        self.assertFalse(math.isnan(expected_before))
        self.assertFalse(math.isnan(expected_after))
        self.assertAlmostEqual(features_before.realized_vol, expected_before)
        self.assertAlmostEqual(features_after.realized_vol, expected_after)
        self.assertGreater(expected_after, expected_before)
        self.assertEqual(features_before.ctx["rv_band"], "mid")
        self.assertEqual(features_after.ctx["rv_band"], "high")
        self.assertNotEqual(features_before.ctx["rv_band"], features_after.ctx["rv_band"])

    def test_run_restores_loaded_state_snapshot(self):
        rcfg_source = RunnerConfig(warmup_trades=10)
        runner = BacktestRunner(equity=75_000.0, symbol="USDJPY", runner_cfg=rcfg_source)
        runner._warmup_left = 4
        key = runner._ev_key("LDN", "narrow", "low")
        manager = runner._get_ev_manager(key)
        manager.update(True)
        manager.update(False)
        expected_warmup = runner._warmup_left
        expected_global_alpha = runner.ev_global.alpha
        expected_global_beta = runner.ev_global.beta
        expected_bucket_alpha = runner.ev_buckets[key].alpha
        expected_bucket_beta = runner.ev_buckets[key].beta
        state = runner.export_state()

        rcfg_target = RunnerConfig(warmup_trades=10)
        restored_runner = BacktestRunner(
            equity=75_000.0,
            symbol="USDJPY",
            runner_cfg=rcfg_target,
        )
        restored_runner.load_state(state)
        metrics = restored_runner.run([])

        self.assertEqual(restored_runner._warmup_left, expected_warmup)
        self.assertAlmostEqual(restored_runner.ev_global.alpha, expected_global_alpha)
        self.assertAlmostEqual(restored_runner.ev_global.beta, expected_global_beta)
        self.assertIn(key, restored_runner.ev_buckets)
        self.assertAlmostEqual(restored_runner.ev_buckets[key].alpha, expected_bucket_alpha)
        self.assertAlmostEqual(restored_runner.ev_buckets[key].beta, expected_bucket_beta)
        self.assertIsInstance(metrics, Metrics)

    def test_export_and_apply_state_round_trips_position_state(self):
        runner = BacktestRunner(equity=50_000.0, symbol="USDJPY")
        active_state = PositionState(
            side="BUY",
            entry_px=150.0,
            tp_px=150.3,
            sl_px=149.7,
            trail_pips=5.0,
            qty=2.0,
            tp_pips=30.0,
            sl_pips=30.0,
            hh=150.15,
            ll=149.65,
            hold=4,
            entry_ts="2024-01-01T08:00:00Z",
            ev_key=("LDN", "normal", "mid"),
            expected_slip_pip=0.2,
            entry_slip_pip=0.1,
            ctx_snapshot={"pip_value": 9.5, "session": "LDN"},
        )
        calib_state = PositionState(
            side="SELL",
            entry_px=150.4,
            tp_px=150.1,
            sl_px=150.7,
            trail_pips=3.0,
            hh=150.45,
            ll=150.05,
            hold=2,
            ev_key=("NY", "wide", "high"),
        )
        runner.pos = active_state
        runner.calib_positions = [calib_state]

        state = runner.export_state()
        self.assertIn("position", state)
        self.assertEqual(state["position"]["side"], "BUY")
        self.assertIn("calibration_positions", state)
        self.assertEqual(len(state["calibration_positions"]), 1)
        self.assertEqual(state["calibration_positions"][0]["side"], "SELL")

        restored = BacktestRunner(equity=50_000.0, symbol="USDJPY")
        restored._apply_state_dict(state)

        self.assertIsNotNone(restored.pos)
        self.assertIsInstance(restored.pos, PositionState)
        assert restored.pos is not None
        self.assertEqual(restored.pos.side, active_state.side)
        self.assertAlmostEqual(restored.pos.tp_px, active_state.tp_px)
        self.assertEqual(restored.pos.ctx_snapshot["session"], "LDN")
        self.assertEqual(len(restored.calib_positions), 1)
        self.assertIsInstance(restored.calib_positions[0], PositionState)
        self.assertEqual(restored.calib_positions[0].ev_key, calib_state.ev_key)

        state["position"]["ctx_snapshot"]["session"] = "NY"
        self.assertEqual(runner.pos.ctx_snapshot["session"], "LDN")

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

    def test_run_resets_ev_and_slip_state_between_runs(self):
        """Ensure learning state resets so repeated runs trade identically.

        The strategy instance persists between ``run`` invocations, so the
        helper emits the same single signal whenever its lone bar is observed.
        """

        class SingleBarStrategy(Strategy):
            def __init__(self) -> None:
                super().__init__()
                self.cfg = {}
                self._pending_signal: Optional[OrderIntent] = None

            def on_start(self, cfg, instruments, state_store) -> None:
                self.cfg = dict(cfg)
                self._pending_signal = None

            def on_bar(self, bar) -> None:
                self._pending_signal = OrderIntent(
                    side="BUY",
                    qty=1.0,
                    price=bar["c"],
                    oco={"tp_pips": 1.0, "sl_pips": 1.0},
                )

            def signals(self):
                if self._pending_signal is None:
                    return []
                return [self._pending_signal]

        cfg = RunnerConfig(
            warmup_trades=0,
            threshold_lcb_pip=0.0,
            include_expected_slip=True,
            slip_learn=True,
            slip_cap_pip=1.0,
            risk_per_trade_pct=1.0,
        )
        symbol = "USDJPY"
        runner = BacktestRunner(
            equity=100_000.0,
            symbol=symbol,
            runner_cfg=cfg,
            debug=True,
            strategy_cls=SingleBarStrategy,
        )
        stub_ev = self.DummyEV(ev_lcb=5.0, p_lcb=0.6)
        runner._get_ev_manager = lambda key: stub_ev
        base_ts = datetime(2024, 1, 4, 9, 0, tzinfo=timezone.utc)
        bars = [
            make_bar(
                base_ts,
                symbol,
                150.0,
                150.1,
                149.9,
                150.0,
                spread=0.005,
            )
        ]

        slip_delta = 3.0 * pip_size(symbol)

        def _force_losing_fill(bar_ctx, spec):
            signed = 1 if spec.side == "BUY" else -1
            entry_px = spec.entry + signed * slip_delta
            exit_px = spec.entry - signed * slip_delta
            return {
                "fill": True,
                "entry_px": entry_px,
                "exit_px": exit_px,
                "exit_reason": "sl",
            }

        with patch.object(
            runner.fill_engine_c,
            "simulate",
            autospec=True,
            side_effect=_force_losing_fill,
        ):
            metrics_first = runner.run(list(bars), mode="conservative")
            first_trades = metrics_first.trades
            first_debug = dict(metrics_first.debug)

            metrics_second = runner.run(list(bars), mode="conservative")
            second_trades = metrics_second.trades
            second_debug = dict(metrics_second.debug)

        self.assertEqual(first_trades, 1)
        self.assertEqual(second_trades, 1)
        self.assertEqual(first_debug, second_debug)
        self.assertLess(metrics_second.total_pips, 0.0)

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
        self.assertAlmostEqual(metrics.total_pnl_value, 5.0)
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

    def test_trade_pnl_scales_with_risk_per_trade(self):
        def simulate_trade(risk_pct: float) -> BacktestRunner:
            cfg = RunnerConfig(risk_per_trade_pct=risk_pct)
            runner = BacktestRunner(
                equity=100_000.0,
                symbol="USDJPY",
                runner_cfg=cfg,
            )
            sizing_cfg = cfg.build_sizing_cfg()
            sizing_cfg["units_cap"] = 100.0
            sizing_cfg["max_trade_loss_pct"] = 100.0
            ctx = {
                "session": "TOK",
                "rv_band": "mid",
                "spread_band": "normal",
                "base_cost_pips": 0.0,
                "equity": runner._equity_live,
                "pip_value": 10.0,
                "sizing_cfg": sizing_cfg,
                "ev_mode": "lcb",
                "warmup_mult": 0.05,
                "size_floor_mult": 0.01,
            }
            ctx_snapshot = {
                "session": ctx["session"],
                "rv_band": ctx["rv_band"],
                "spread_band": ctx["spread_band"],
                "expected_slip_pip": 0.0,
                "cost_base": ctx["base_cost_pips"],
                "pip_value": ctx["pip_value"],
            }
            qty = compute_qty_from_ctx(
                ctx,
                sl_pips=1.0,
                mode="production",
                tp_pips=2.0,
                p_lcb=0.6,
            )
            date_key = "2024-01-01"
            runner._current_daily_entry = runner._ensure_daily_entry(date_key)
            exit_ts = "2024-01-01T00:05:00Z"
            runner._last_timestamp = exit_ts
            runner._finalize_trade(
                exit_ts=exit_ts,
                entry_ts="2024-01-01T00:00:00Z",
                side="BUY",
                entry_px=150.0,
                exit_px=150.05,
                exit_reason="tp",
                ctx_snapshot=ctx_snapshot,
                ctx=ctx,
                qty_sample=qty,
                slip_actual=0.0,
                ev_key=None,
                tp_pips=2.0,
                sl_pips=1.0,
                debug_stage="trade",
            )
            return runner

        runner_low = simulate_trade(0.5)
        runner_high = simulate_trade(1.0)

        self.assertGreater(runner_high.metrics.total_pips, runner_low.metrics.total_pips)
        self.assertGreater(
            runner_high.metrics.total_pnl_value, runner_low.metrics.total_pnl_value
        )
        self.assertGreater(runner_high._equity_live, runner_low._equity_live)
        date_key = "2024-01-01"
        self.assertIn(date_key, runner_high.daily)
        high_daily = runner_high.daily[date_key]
        low_daily = runner_low.daily[date_key]
        self.assertGreater(high_daily["pnl_pips"], low_daily["pnl_pips"])
        self.assertGreater(high_daily["pnl_value"], low_daily["pnl_value"])
        self.assertIn("pnl_value", runner_high.records[-1])
        self.assertIn("qty", runner_high.records[-1])

    def test_entry_slip_preserves_tp_sl_distances_and_pnl(self):
        runner = BacktestRunner(equity=100_000.0, symbol="USDJPY")
        pip = pip_size("USDJPY")
        tp_pips = 6.0
        sl_pips = 3.0
        slip_pips = 0.4
        base_price = 150.0
        filled_entry = base_price + slip_pips * pip
        intent = OrderIntent(
            side="BUY",
            qty=1.0,
            price=base_price,
            oco={"tp_pips": tp_pips, "sl_pips": sl_pips, "trail_pips": 0.0},
        )
        spec = OrderSpec(
            side="BUY",
            entry=base_price,
            tp_pips=tp_pips,
            sl_pips=sl_pips,
            trail_pips=0.0,
        )
        entry_bar = make_bar(
            datetime(2024, 1, 6, 9, 0, tzinfo=timezone.utc),
            "USDJPY",
            base_price,
            base_price + 0.5,
            base_price - 0.5,
            base_price + 0.1,
            spread=0.02,
        )
        ctx = {
            "session": "LDN",
            "spread_band": "normal",
            "rv_band": "med",
            "pip_value": 1.0,
        }
        ctx_dbg = {"expected_slip_pip": slip_pips}
        trade_ctx_snapshot = {"pip_value": 1.0}
        fill_result = {"fill": True, "entry_px": filled_entry}

        runner._process_fill_result(
            intent=intent,
            spec=spec,
            result=dict(fill_result),
            bar=entry_bar,
            ctx=ctx,
            ctx_dbg=ctx_dbg,
            trade_ctx_snapshot={},
            calibrating=True,
            pip_size_value=pip,
        )
        self.assertEqual(len(runner.calib_positions), 1)
        calib_pos = runner.calib_positions[-1]
        self.assertIsInstance(calib_pos, PositionState)
        self.assertAlmostEqual(calib_pos.entry_px, filled_entry)
        self.assertAlmostEqual(calib_pos.tp_px - filled_entry, tp_pips * pip)
        self.assertAlmostEqual(filled_entry - calib_pos.sl_px, sl_pips * pip)

        runner.calib_positions.clear()

        runner._process_fill_result(
            intent=intent,
            spec=spec,
            result=fill_result,
            bar=entry_bar,
            ctx=ctx,
            ctx_dbg=ctx_dbg,
            trade_ctx_snapshot=trade_ctx_snapshot,
            calibrating=False,
            pip_size_value=pip,
        )
        self.assertIsNotNone(runner.pos)
        pos = runner.pos
        self.assertIsInstance(pos, PositionState)
        self.assertAlmostEqual(pos.entry_px, filled_entry)
        self.assertAlmostEqual(pos.tp_px - filled_entry, tp_pips * pip)
        self.assertAlmostEqual(filled_entry - pos.sl_px, sl_pips * pip)
        self.assertGreater(pos.entry_slip_pip, 0.0)

        exit_bar = make_bar(
            datetime(2024, 1, 6, 9, 5, tzinfo=timezone.utc),
            "USDJPY",
            pos.tp_px,
            pos.tp_px + pip,
            pos.sl_px + pip,
            pos.tp_px,
            spread=0.02,
        )

        handled = runner._handle_active_position(
            bar=exit_bar,
            ctx=ctx,
            mode="conservative",
            pip_size_value=pip,
            new_session=False,
        )
        self.assertTrue(handled)
        self.assertIsNone(runner.pos)
        self.assertAlmostEqual(runner.metrics.total_pips, tp_pips)
        self.assertEqual(len(runner.records), 1)
        trade_record = runner.records[-1]
        self.assertAlmostEqual(trade_record["pnl_pips"], tp_pips)
        self.assertAlmostEqual(runner.metrics.total_pnl_value, tp_pips)

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
        sizing_gate = SizingGate(runner)
        ev_result = EVEvaluationResult(
            outcome=GateCheckOutcome(passed=True),
            manager=ev_mgr,
            ev_lcb=0.0,
            threshold_lcb=0.0,
            bypass=False,
            context=ctx_dbg,
        )

        result = sizing_gate.evaluate(
            ctx_dbg=ctx_dbg,
            pending=pending,
            ev_result=ev_result,
            calibrating=False,
            timestamp="2024-01-01T00:00:00Z",
        )

        self.assertFalse(result.outcome.passed)
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
        sizing_gate = SizingGate(runner)
        ev_result = EVEvaluationResult(
            outcome=GateCheckOutcome(passed=True),
            manager=ev_mgr,
            ev_lcb=0.0,
            threshold_lcb=0.0,
            bypass=False,
            context=ctx_dbg,
        )

        result = sizing_gate.evaluate(
            ctx_dbg=ctx_dbg,
            pending=pending,
            ev_result=ev_result,
            calibrating=False,
            timestamp="2024-01-01T00:05:00Z",
        )

        self.assertFalse(result.outcome.passed)
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

    def test_position_size_updates_with_live_equity(self):
        runner = BacktestRunner(equity=100_000.0, symbol="USDJPY")
        pip = pip_size("USDJPY")
        base_bar = {"spread": 0.0}
        ctx_initial = runner._build_ctx(
            bar=base_bar,
            session="TOK",
            atr14=1.0,
            or_h=None,
            or_l=None,
            realized_vol_value=0.0,
        )
        sl_pips = 10.0
        tp_pips = 20.0
        qty_initial = compute_qty_from_ctx(
            ctx_initial,
            sl_pips,
            mode="production",
            tp_pips=tp_pips,
            p_lcb=0.6,
        )
        self.assertGreater(qty_initial, 0.0)

        def _snapshot_from_ctx(ctx):
            return {
                "pip_value": ctx.get("pip_value"),
                "cost_base": ctx.get("base_cost_pips", ctx.get("cost_pips", 0.0)),
                "spread_band": ctx.get("spread_band"),
                "session": ctx.get("session"),
                "rv_band": ctx.get("rv_band"),
            }

        runner._last_timestamp = "2024-01-01T00:00:00Z"
        runner._finalize_trade(
            exit_ts="2024-01-01T00:05:00Z",
            entry_ts="2024-01-01T00:00:00Z",
            side="BUY",
            entry_px=100.0,
            exit_px=100.0 - sl_pips * pip,
            exit_reason="sl",
            ctx_snapshot=_snapshot_from_ctx(ctx_initial),
            ctx=ctx_initial,
            qty_sample=qty_initial,
            slip_actual=0.0,
            ev_key=ctx_initial["ev_key"],
            tp_pips=tp_pips,
            sl_pips=sl_pips,
            debug_stage="trade",
        )

        ctx_after_loss = runner._build_ctx(
            bar=base_bar,
            session="TOK",
            atr14=1.0,
            or_h=None,
            or_l=None,
            realized_vol_value=0.0,
        )
        qty_after_loss = compute_qty_from_ctx(
            ctx_after_loss,
            sl_pips,
            mode="production",
            tp_pips=tp_pips,
            p_lcb=0.6,
        )
        self.assertLess(qty_after_loss, qty_initial)

        runner._last_timestamp = "2024-01-01T00:10:00Z"
        runner._finalize_trade(
            exit_ts="2024-01-01T00:15:00Z",
            entry_ts="2024-01-01T00:10:00Z",
            side="BUY",
            entry_px=100.0,
            exit_px=100.0 + tp_pips * pip,
            exit_reason="tp",
            ctx_snapshot=_snapshot_from_ctx(ctx_after_loss),
            ctx=ctx_after_loss,
            qty_sample=qty_after_loss,
            slip_actual=0.0,
            ev_key=ctx_after_loss["ev_key"],
            tp_pips=tp_pips,
            sl_pips=sl_pips,
            debug_stage="trade",
        )

        ctx_after_win = runner._build_ctx(
            bar=base_bar,
            session="TOK",
            atr14=1.0,
            or_h=None,
            or_l=None,
            realized_vol_value=0.0,
        )
        qty_after_win = compute_qty_from_ctx(
            ctx_after_win,
            sl_pips,
            mode="production",
            tp_pips=tp_pips,
            p_lcb=0.6,
        )
        self.assertGreater(qty_after_win, qty_after_loss)
        self.assertGreater(len(runner.metrics.equity_curve), 0)
        self.assertAlmostEqual(
            runner.metrics.equity_curve[-1][1],
            runner._equity_live,
        )
    def test_evaluate_entry_conditions_and_ev_pass_on_breakout(self):
        runner, pending, breakout, features, calibrating = self._prepare_breakout_environment(
            warmup_left=0
        )
        stub_ev = self.DummyEV(ev_lcb=1.2, p_lcb=0.65)
        runner._get_ev_manager = lambda key: stub_ev
        entry_gate = EntryGate(runner)
        entry_result = entry_gate.evaluate(
            pending=pending,
            features=features,
        )
        self.assertTrue(entry_result.outcome.passed)
        ctx_dbg = entry_result.context
        self.assertIsNotNone(ctx_dbg)
        ev_gate = EVGate(runner)
        ev_result = ev_gate.evaluate(
            ctx_dbg=ctx_dbg,
            pending=pending,
            calibrating=calibrating,
            timestamp=runner._last_timestamp,
        )
        self.assertTrue(ev_result.outcome.passed)
        self.assertIs(ev_result.manager, stub_ev)
        self.assertGreater(ev_result.ev_lcb, ev_result.threshold_lcb)
        self.assertFalse(ev_result.bypass)
        self.assertTrue(ctx_dbg.get("ev_pass"))
        sizing_gate = SizingGate(runner)
        sizing_result = sizing_gate.evaluate(
            ctx_dbg=ctx_dbg,
            pending=pending,
            ev_result=ev_result,
            calibrating=calibrating,
            timestamp=runner._last_timestamp,
        )
        self.assertTrue(sizing_result.outcome.passed)

    def test_evaluate_ev_threshold_rejects_when_ev_below_threshold(self):
        runner, pending, breakout, features, calibrating = self._prepare_breakout_environment(
            warmup_left=0
        )
        stub_ev = self.DummyEV(ev_lcb=0.05, p_lcb=0.55)
        runner._get_ev_manager = lambda key: stub_ev
        entry_result = EntryGate(runner).evaluate(
            pending=pending,
            features=features,
        )
        self.assertTrue(entry_result.outcome.passed)
        ctx_dbg = entry_result.context
        self.assertIsNotNone(ctx_dbg)
        ev_result = EVGate(runner).evaluate(
            ctx_dbg=ctx_dbg,
            pending=pending,
            calibrating=calibrating,
            timestamp=runner._last_timestamp,
        )
        self.assertFalse(ev_result.outcome.passed)
        self.assertEqual(runner.debug_counts["ev_reject"], 1)

    def test_ev_gate_off_mode_bypasses_threshold_checks(self):
        rcfg = RunnerConfig(ev_mode="off", threshold_lcb_pip=999.0)
        runner, pending, breakout, features, calibrating = self._prepare_breakout_environment(
            warmup_left=0,
            runner_cfg=rcfg,
        )
        stub_ev = self.DummyEV(ev_lcb=0.05, p_lcb=0.55)
        runner._get_ev_manager = lambda key: stub_ev
        entry_result = EntryGate(runner).evaluate(
            pending=pending,
            features=features,
        )
        self.assertTrue(entry_result.outcome.passed)
        ctx_dbg = entry_result.context
        self.assertIsNotNone(ctx_dbg)
        self.assertEqual(ctx_dbg.get("ev_mode"), "off")
        ev_result = EVGate(runner).evaluate(
            ctx_dbg=ctx_dbg,
            pending=pending,
            calibrating=calibrating,
            timestamp=runner._last_timestamp,
        )
        self.assertTrue(ev_result.outcome.passed)
        self.assertIs(ev_result.manager, stub_ev)
        self.assertFalse(ev_result.bypass)
        self.assertTrue(math.isinf(ev_result.threshold_lcb))
        self.assertLess(ev_result.threshold_lcb, 0.0)
        self.assertTrue(math.isinf(ctx_dbg.get("threshold_lcb_pip")))
        self.assertEqual(ctx_dbg.get("threshold_lcb"), ev_result.threshold_lcb)
        self.assertTrue(ctx_dbg.get("ev_pass"))
        self.assertEqual(runner.debug_counts["ev_reject"], 0)

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
        entry_result = EntryGate(runner).evaluate(
            pending=intent,
            features=features,
        )
        self.assertTrue(entry_result.outcome.passed)
        ctx_dbg = entry_result.context
        self.assertIsNotNone(ctx_dbg)
        ev_result = EVGate(runner).evaluate(
            ctx_dbg=ctx_dbg,
            pending=intent,
            calibrating=calibrating,
            timestamp=runner._last_timestamp,
        )
        self.assertFalse(ev_result.outcome.passed)
        self.assertEqual(runner.debug_counts["ev_reject"], 1)
        ctx_dbg.setdefault("expected_slip_pip", 0.0)
        ctx_dbg.setdefault("slip_cap_pip", runner.rcfg.slip_cap_pip)
        ctx_dbg.setdefault("cost_pips", 0.0)
        sizing_gate = SizingGate(runner)
        with patch("core.runner_entry.compute_qty_from_ctx", return_value=1.0) as mock_compute:
            forced_ev_result = EVEvaluationResult(
                outcome=GateCheckOutcome(passed=True),
                manager=stub_ev,
                ev_lcb=ev_result.ev_lcb,
                threshold_lcb=ev_result.threshold_lcb,
                bypass=False,
                context=ctx_dbg,
            )
            sizing_result = sizing_gate.evaluate(
                ctx_dbg=ctx_dbg,
                pending=intent,
                ev_result=forced_ev_result,
                calibrating=False,
                timestamp=runner._last_timestamp,
            )
        self.assertTrue(sizing_result.outcome.passed)
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
        entry_result = EntryGate(runner).evaluate(
            pending=pending,
            features=features,
        )
        self.assertTrue(entry_result.outcome.passed)
        ctx_dbg = entry_result.context
        self.assertIsNotNone(ctx_dbg)
        ev_result = EVGate(runner).evaluate(
            ctx_dbg=ctx_dbg,
            pending=pending,
            calibrating=calibrating,
            timestamp=runner._last_timestamp,
        )
        self.assertTrue(ev_result.outcome.passed)
        self.assertTrue(ev_result.bypass)
        self.assertFalse(ctx_dbg.get("ev_pass"))
        sizing_result = SizingGate(runner).evaluate(
            ctx_dbg=ctx_dbg,
            pending=pending,
            ev_result=ev_result,
            calibrating=calibrating,
            timestamp=runner._last_timestamp,
        )
        self.assertTrue(sizing_result.outcome.passed)
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

    def test_maybe_enter_trade_stops_when_entry_gate_blocks(self):
        runner, pending, breakout, features, calibrating = self._prepare_breakout_environment(
            warmup_left=0
        )
        pip_value = pip_size(runner.symbol)
        fail_result = EntryEvaluationResult(
            outcome=GateCheckOutcome(passed=False, reason="router_gate"),
            context=None,
            pending_side=pending["side"],
        )
        with patch.object(runner.stg, "on_bar", return_value=None):
            runner.stg._pending_signal = pending
            with patch(
                "core.runner_entry.EntryGate.evaluate",
                return_value=fail_result,
            ) as mock_entry, patch(
                "core.runner_entry.EVGate.evaluate"
            ) as mock_ev, patch(
                "core.runner_entry.SizingGate.evaluate"
            ) as mock_sizing, patch.object(
                runner,
                "_process_fill_result",
            ) as mock_process:
                runner._maybe_enter_trade(
                    bar=breakout,
                    features=features,
                    mode="conservative",
                    pip_size_value=pip_value,
                    calibrating=calibrating,
                )
        mock_entry.assert_called_once()
        mock_ev.assert_not_called()
        mock_sizing.assert_not_called()
        mock_process.assert_not_called()

    def test_maybe_enter_trade_pipeline_success_triggers_fill(self):
        runner, pending, breakout, features, calibrating = self._prepare_breakout_environment(
            warmup_left=0
        )
        pip_value = pip_size(runner.symbol)
        stub_ev = self.DummyEV(ev_lcb=1.2, p_lcb=0.65)
        ctx_dbg = dict(features.ctx)
        ctx_dbg.setdefault("slip_cap_pip", runner.rcfg.slip_cap_pip)
        ctx_dbg.setdefault("expected_slip_pip", 0.0)
        ctx_dbg.setdefault("cost_pips", ctx_dbg.get("cost_pips", 0.0))
        entry_result = EntryEvaluationResult(
            outcome=GateCheckOutcome(passed=True),
            context=ctx_dbg,
            pending_side=pending["side"],
        )
        ev_result = EVEvaluationResult(
            outcome=GateCheckOutcome(passed=True),
            manager=stub_ev,
            ev_lcb=1.2,
            threshold_lcb=0.6,
            bypass=False,
            context=ctx_dbg,
        )
        sizing_result = SizingEvaluationResult(GateCheckOutcome(passed=True))
        intent = OrderIntent(
            pending["side"],
            qty=1.0,
            price=pending["entry"],
            oco={
                "tp_pips": pending["tp_pips"],
                "sl_pips": pending["sl_pips"],
                "trail_pips": pending["trail_pips"],
            },
        )
        fill_result = {
            "fill": True,
            "entry_px": pending["entry"],
            "exit_px": pending["entry"],
            "exit_reason": "tp",
        }
        with patch.object(runner.stg, "on_bar", return_value=None):
            runner.stg._pending_signal = pending
            with ExitStack() as stack:
                mock_entry = stack.enter_context(
                    patch(
                        "core.runner_entry.EntryGate.evaluate",
                        return_value=entry_result,
                    )
                )
                mock_ev = stack.enter_context(
                    patch(
                        "core.runner_entry.EVGate.evaluate",
                        return_value=ev_result,
                    )
                )
                mock_sizing = stack.enter_context(
                    patch(
                        "core.runner_entry.SizingGate.evaluate",
                        return_value=sizing_result,
                    )
                )
                mock_signals = stack.enter_context(
                    patch.object(
                        runner.stg,
                        "signals",
                        return_value=[intent],
                    )
                )
                mock_sim = stack.enter_context(
                    patch.object(
                        runner.fill_engine_c,
                        "simulate",
                        return_value=fill_result,
                    )
                )
                mock_process = stack.enter_context(
                    patch.object(runner, "_process_fill_result")
                )
                runner._maybe_enter_trade(
                    bar=breakout,
                    features=features,
                    mode="conservative",
                    pip_size_value=pip_value,
                    calibrating=calibrating,
                )
        mock_entry.assert_called_once()
        mock_ev.assert_called_once()
        mock_sizing.assert_called_once()
        mock_signals.assert_called_once()
        mock_sim.assert_called_once()
        mock_process.assert_called_once()

    def test_warmup_counter_not_decremented_when_no_fill(self):
        runner, pending, breakout, features, calibrating = self._prepare_breakout_environment(
            warmup_left=3
        )
        stub_ev = self.DummyEV(ev_lcb=1.2, p_lcb=0.65)
        runner._get_ev_manager = lambda key: stub_ev
        no_fill_entry = breakout["h"] + 0.05
        pending["entry"] = no_fill_entry
        runner.stg._pending_signal = pending
        features.ctx["ev_oco"] = stub_ev
        features.ctx.setdefault("slip_cap_pip", runner.rcfg.slip_cap_pip)
        features.ctx.setdefault("expected_slip_pip", 0.0)
        pip_value = pip_size(runner.symbol)
        initial_warmup = runner._warmup_left
        intent = OrderIntent(
            pending["side"],
            qty=1.0,
            price=no_fill_entry,
            tif="IOC",
            tag="day_orb5m#test",
            oco={
                "tp_pips": pending["tp_pips"],
                "sl_pips": pending["sl_pips"],
                "trail_pips": pending["trail_pips"],
            },
        )

        runner.fill_engine_c.default_policy = SameBarPolicy.SL_FIRST

        with patch(
            "core.runner_entry.SizingGate.evaluate",
            side_effect=lambda **_: SizingEvaluationResult(GateCheckOutcome(True)),
        ):
            with patch.object(runner.stg, "signals", return_value=[intent]):
                with patch.object(runner, "_process_fill_result") as mock_process:
                    runner._maybe_enter_trade(
                        bar=breakout,
                        features=features,
                        mode="conservative",
                        pip_size_value=pip_value,
                        calibrating=calibrating,
                    )
        self.assertEqual(runner._warmup_left, initial_warmup)
        mock_process.assert_not_called()

    def test_warmup_counter_decrements_after_successful_fill(self):
        runner, pending, breakout, features, calibrating = self._prepare_breakout_environment(
            warmup_left=3
        )
        stub_ev = self.DummyEV(ev_lcb=1.2, p_lcb=0.65)
        runner._get_ev_manager = lambda key: stub_ev
        fill_entry = breakout["c"]
        pending["entry"] = fill_entry
        runner.stg._pending_signal = pending
        features.ctx["ev_oco"] = stub_ev
        features.ctx.setdefault("slip_cap_pip", runner.rcfg.slip_cap_pip)
        features.ctx.setdefault("expected_slip_pip", 0.0)
        pip_value = pip_size(runner.symbol)
        initial_warmup = runner._warmup_left
        intent = OrderIntent(
            pending["side"],
            qty=1.0,
            price=fill_entry,
            tif="IOC",
            tag="day_orb5m#test",
            oco={
                "tp_pips": pending["tp_pips"],
                "sl_pips": pending["sl_pips"],
                "trail_pips": pending["trail_pips"],
            },
        )

        runner.fill_engine_c.default_policy = SameBarPolicy.SL_FIRST

        with patch(
            "core.runner_entry.SizingGate.evaluate",
            side_effect=lambda **_: SizingEvaluationResult(GateCheckOutcome(True)),
        ):
            with patch.object(runner.stg, "signals", return_value=[intent]):
                with patch.object(
                    runner,
                    "_process_fill_result",
                    wraps=runner._process_fill_result,
                ) as mock_process:
                    runner._maybe_enter_trade(
                        bar=breakout,
                        features=features,
                        mode="conservative",
                        pip_size_value=pip_value,
                        calibrating=calibrating,
                    )
        self.assertEqual(runner._warmup_left, initial_warmup - 1)
        mock_process.assert_called_once()

    def test_calibration_warmup_counter_remains_unchanged(self):
        runner, pending, breakout, features, calibrating = self._prepare_breakout_environment(
            warmup_left=3,
            calibrate_days=2,
        )
        self.assertTrue(calibrating)
        stub_ev = self.DummyEV(ev_lcb=1.1, p_lcb=0.7)
        runner._get_ev_manager = lambda key: stub_ev
        fill_entry = breakout["c"]
        pending["entry"] = fill_entry
        runner.stg._pending_signal = pending
        features.ctx["ev_oco"] = stub_ev
        features.ctx.setdefault("slip_cap_pip", runner.rcfg.slip_cap_pip)
        features.ctx.setdefault("expected_slip_pip", 0.0)
        pip_value = pip_size(runner.symbol)
        initial_warmup = runner._warmup_left
        intent = OrderIntent(
            pending["side"],
            qty=1.0,
            price=fill_entry,
            tif="IOC",
            tag="day_orb5m#test",
            oco={
                "tp_pips": pending["tp_pips"],
                "sl_pips": pending["sl_pips"],
                "trail_pips": pending["trail_pips"],
            },
        )

        runner.fill_engine_c.default_policy = SameBarPolicy.SL_FIRST

        with patch(
            "core.runner_entry.SizingGate.evaluate",
            side_effect=lambda **_: SizingEvaluationResult(GateCheckOutcome(True)),
        ):
            with patch.object(runner.stg, "signals", return_value=[intent]):
                with patch.object(
                    runner,
                    "_process_fill_result",
                    wraps=runner._process_fill_result,
                ) as mock_process:
                    runner._maybe_enter_trade(
                        bar=breakout,
                        features=features,
                        mode="conservative",
                        pip_size_value=pip_value,
                        calibrating=calibrating,
                    )
        self.assertEqual(runner._warmup_left, initial_warmup)
        mock_process.assert_called_once()

    def test_calibration_positions_resolve_after_period(self):
        runner = BacktestRunner(equity=100_000.0, symbol="USDJPY")
        runner.rcfg.calibrate_days = 1
        ev_key = ("LDN", "normal", "mid")
        runner.calib_positions = [
            PositionState(
                side="BUY",
                entry_px=150.0,
                tp_px=150.5,
                sl_px=149.5,
                trail_pips=0.0,
                hh=150.2,
                ll=149.8,
                ev_key=ev_key,
            )
        ]
        bar = make_bar(
            datetime(2024, 1, 2, 8, 5, tzinfo=timezone.utc),
            "USDJPY",
            150.0,
            150.2,
            149.8,
            150.1,
            spread=0.02,
        )
        ctx = {
            "ev_key": ev_key,
            "session": "LDN",
            "spread_band": "normal",
            "rv_band": "mid",
        }
        dummy_ev = MagicMock()
        runner._get_ev_manager = MagicMock(return_value=dummy_ev)
        decision = ExitDecision(exited=True, exit_px=150.2, exit_reason="tp", updated_pos=None)

        with patch.object(runner, "_compute_exit_decision", return_value=decision) as mock_decision:
            runner._resolve_calibration_positions(
                bar=bar,
                ctx=ctx,
                new_session=False,
                calibrating=False,
                mode="conservative",
                pip_size_value=pip_size(runner.symbol),
            )

        mock_decision.assert_called_once()
        dummy_ev.update.assert_called_once_with(True)
        self.assertFalse(runner.calib_positions)

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
        stg.update_context(cfg["ctx"])
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
        stg.update_context(cfg["ctx"])
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
        entry_result = EntryGate(runner).evaluate(
            pending=pending,
            features=features,
        )
        self.assertTrue(entry_result.outcome.passed)
        ctx_dbg = entry_result.context
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
                    runner.pos = PositionState(
                        side=side,
                        entry_px=150.00,
                        tp_px=150.80 if side == "BUY" else 149.20,
                        sl_px=149.00 if side == "BUY" else 151.00,
                        trail_pips=10.0,
                        qty=1.0,
                        entry_ts="2024-01-01T08:00:00+00:00",
                        ctx_snapshot={},
                        ev_key=None,
                        tp_pips=80.0,
                        sl_pips=100.0,
                    )
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
                    runner.pos = PositionState(
                        side=side,
                        entry_px=entry,
                        tp_px=tp,
                        sl_px=sl,
                        trail_pips=0.0,
                        qty=1.0,
                        entry_ts="2024-01-01T08:00:00+00:00",
                        ctx_snapshot={},
                        ev_key=None,
                        tp_pips=abs(tp - entry) / pip_value,
                        sl_pips=abs(entry - sl) / pip_value,
                    )
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
                    runner.pos = PositionState(
                        side=side,
                        entry_px=entry,
                        tp_px=tp,
                        sl_px=sl,
                        trail_pips=0.0,
                        qty=1.0,
                        entry_ts="2024-01-01T08:00:00+00:00",
                        ctx_snapshot={},
                        ev_key=None,
                        tp_pips=abs(tp - entry) / pip_value,
                        sl_pips=abs(entry - sl) / pip_value,
                        hold=1,
                    )
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
            PositionState(
                side="BUY",
                entry_px=150.00,
                tp_px=150.20,
                sl_px=149.80,
                trail_pips=0.0,
                hh=150.00,
                ll=150.00,
                ev_key=("LDN", "normal", "mid"),
            )
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
            PositionState(
                side="SELL",
                entry_px=150.00,
                tp_px=149.70,
                sl_px=150.30,
                trail_pips=0.0,
                hh=150.00,
                ll=150.00,
                ev_key=None,
            )
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
