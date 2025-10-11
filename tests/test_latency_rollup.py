from datetime import datetime, timezone

from analysis.latency_rollup import LatencySample, aggregate


def _sample(ts: str, latency_ms: float, status: str = "success") -> LatencySample:
    return LatencySample(
        timestamp=datetime.fromisoformat(ts).replace(tzinfo=timezone.utc),
        latency_ms=latency_ms,
        status=status,
    )


def test_aggregate_groups_into_hour_windows():
    samples = [
        _sample("2026-06-29T00:05:00", 120.0),
        _sample("2026-06-29T00:35:00", 80.0),
        _sample("2026-06-29T01:10:00", 150.0, status="error"),
    ]

    rollups = aggregate(samples, window="1H")

    assert len(rollups) == 2
    first, second = rollups
    assert first.count == 2
    assert first.failure_count == 0
    assert abs(first.p95_ms - 118.0) < 1e-6
    assert second.count == 1
    assert second.failure_count == 1
    assert second.failure_rate == 1.0


def test_percentiles_interp_with_multiple_samples():
    samples = [
        _sample("2026-06-29T00:00:00", 100.0),
        _sample("2026-06-29T00:10:00", 200.0),
        _sample("2026-06-29T00:20:00", 300.0),
        _sample("2026-06-29T00:30:00", 400.0),
    ]

    rollup = aggregate(samples, window="1H")[0]

    assert rollup.p50_ms == 250.0
    assert rollup.failure_rate == 0.0
    assert rollup.max_ms == 400.0


def test_minute_window_supported():
    samples = [
        _sample("2026-06-29T00:00:00", 10.0),
        _sample("2026-06-29T00:00:30", 20.0),
        _sample("2026-06-29T00:01:10", 30.0),
    ]

    rollups = aggregate(samples, window="1M")

    assert len(rollups) == 2
    assert rollups[0].count == 2
    assert rollups[1].count == 1
