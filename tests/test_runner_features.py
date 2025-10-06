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
