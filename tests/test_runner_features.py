from datetime import datetime, timezone, timedelta
import math

import pytest

from core.runner import BacktestRunner
from core.runner_features import FeaturePipeline, RunnerContext


def make_bar(ts: datetime, price: float) -> dict:
    return {
        "timestamp": ts.isoformat().replace("+00:00", "Z"),
        "symbol": "USDJPY",
        "tf": "5m",
        "o": price,
        "h": price + 0.1,
        "l": price - 0.1,
        "c": price,
        "v": 1000.0,
        "spread": 0.02,
    }


@pytest.fixture
def runner() -> BacktestRunner:
    return BacktestRunner(equity=100_000.0, symbol="USDJPY")


def test_pipeline_returns_runner_context_and_updates_strategy(runner: BacktestRunner) -> None:
    pipeline = FeaturePipeline(
        rcfg=runner.rcfg,
        window=runner.window,
        session_bars=runner.session_bars,
        rv_hist=runner.rv_hist,
        ctx_builder=runner._build_ctx,
        context_consumer=runner.stg.update_context,
    )
    ts = datetime(2024, 1, 1, 8, 0, tzinfo=timezone.utc)
    bar = make_bar(ts, 150.0)
    features, ctx = pipeline.compute(
        bar,
        session="LDN",
        new_session=True,
        calibrating=False,
    )

    assert isinstance(ctx, RunnerContext)
    assert features.ctx is ctx
    assert features.entry_ctx.session == "LDN"
    assert features.entry_ctx.rv_band == ctx["rv_band"]
    assert runner.stg.runtime_ctx == ctx.to_dict()
    assert ctx["session"] == "LDN"
    assert "rv_band" in ctx
    assert ctx.get("calibrating") is None


def test_pipeline_sanitises_invalid_micro_features(runner: BacktestRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("core.runner_features.calc_micro_zscore", lambda bars: math.nan)
    monkeypatch.setattr("core.runner_features.calc_micro_trend", lambda bars: float("inf"))
    monkeypatch.setattr("core.runner_features.calc_trend_score", lambda bars: math.nan)
    monkeypatch.setattr("core.runner_features.calc_pullback", lambda bars: math.nan)

    pipeline = FeaturePipeline(
        rcfg=runner.rcfg,
        window=runner.window,
        session_bars=runner.session_bars,
        rv_hist=runner.rv_hist,
        ctx_builder=runner._build_ctx,
        context_consumer=runner.stg.update_context,
    )
    ts = datetime(2024, 1, 1, 8, 0, tzinfo=timezone.utc)
    bar = make_bar(ts, 150.0)

    features, ctx = pipeline.compute(
        bar,
        session="LDN",
        new_session=True,
        calibrating=True,
    )

    assert features.micro_zscore == 0.0
    assert features.micro_trend == 0.0
    assert features.trend_score == 0.0
    assert features.pullback == 0.0
    assert ctx["threshold_lcb_pip"] == -1e9
    assert ctx["calibrating"] is True
    assert features.entry_ctx.calibrating is True
    assert features.entry_ctx.threshold_lcb_pip == -1e9


def test_runner_context_behaves_like_mapping() -> None:
    ctx = RunnerContext({"session": "LDN", "rv_band": "mid"})
    assert dict(ctx.items()) == {"session": "LDN", "rv_band": "mid"}

    ctx["spread_band"] = "narrow"
    assert "spread_band" in ctx
    assert len(ctx) == 3

    removed = ctx.setdefault("rv_band", "high")
    assert removed == "mid"
    assert ctx["rv_band"] == "mid"

    ctx.setdefault("calibrating", True)
    assert ctx["calibrating"] is True

    del ctx["session"]
    assert "session" not in ctx
    assert ctx.to_dict() == {"rv_band": "mid", "spread_band": "narrow", "calibrating": True}


def test_pipeline_updates_realized_vol_history_with_sanitized_values(
    runner: BacktestRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_realized_vol(bars, n):  # type: ignore[no-untyped-def]
        if bars is not None:
            assert len(bars) == n + 1
        return math.nan

    monkeypatch.setattr("core.runner_features.realized_vol", fake_realized_vol)
    pipeline = FeaturePipeline(
        rcfg=runner.rcfg,
        window=runner.window,
        session_bars=runner.session_bars,
        rv_hist=runner.rv_hist,
        ctx_builder=runner._build_ctx,
        context_consumer=runner.stg.update_context,
    )

    base_ts = datetime(2024, 1, 1, 8, 0, tzinfo=timezone.utc)
    for idx in range(13):
        ts = base_ts + timedelta(minutes=5 * idx)
        bar = make_bar(ts, 150.0 + idx * 0.01)
        pipeline.compute(
            bar,
            session="LDN",
            new_session=idx == 0,
            calibrating=False,
        )

    history = list(runner.rv_hist["LDN"])
    assert len(history) == 13
    assert all(value == 0.0 for value in history)


def test_pipeline_resets_session_window_on_new_session(runner: BacktestRunner) -> None:
    pipeline = FeaturePipeline(
        rcfg=runner.rcfg,
        window=runner.window,
        session_bars=runner.session_bars,
        rv_hist=runner.rv_hist,
        ctx_builder=runner._build_ctx,
        context_consumer=runner.stg.update_context,
    )

    base_ts = datetime(2024, 1, 1, 8, 0, tzinfo=timezone.utc)
    first_bar = make_bar(base_ts, 150.0)
    second_bar = make_bar(base_ts + timedelta(minutes=5), 150.1)
    third_bar = make_bar(base_ts + timedelta(minutes=10), 150.2)

    pipeline.compute(first_bar, session="LDN", new_session=True, calibrating=False)
    pipeline.compute(second_bar, session="LDN", new_session=False, calibrating=False)
    assert len(runner.session_bars) == 2

    features, ctx = pipeline.compute(
        third_bar,
        session="LDN",
        new_session=True,
        calibrating=False,
    )

    assert len(runner.session_bars) == 1
    assert runner.session_bars[0]["c"] == third_bar["c"]
    assert features.bar_input["window"] == runner.session_bars[: runner.rcfg.or_n]
    assert ctx["session"] == "LDN"
