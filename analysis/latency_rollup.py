"""Latency rollup helpers for observability automation."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Iterator, List, Sequence

__all__ = [
    "LatencySample",
    "LatencyRollup",
    "aggregate",
]


@dataclass(frozen=True)
class LatencySample:
    """Single latency observation."""

    timestamp: datetime
    latency_ms: float
    status: str = "success"
    detail: str | None = None
    source: str | None = None

    def is_failure(self) -> bool:
        return self.status not in {"success", "ok", "stable"}


@dataclass(frozen=True)
class LatencyRollup:
    """Aggregated latency metrics for a fixed window."""

    window_start: datetime
    window_end: datetime
    count: int
    failure_count: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float

    @property
    def failure_rate(self) -> float:
        if self.count == 0:
            return 0.0
        return self.failure_count / self.count

    def as_csv_row(self) -> dict[str, object]:
        return {
            "hour_utc": _format_ts(self.window_start),
            "window_end_utc": _format_ts(self.window_end),
            "count": self.count,
            "failure_count": self.failure_count,
            "failure_rate": round(self.failure_rate, 6),
            "p50_ms": round(self.p50_ms, 3),
            "p95_ms": round(self.p95_ms, 3),
            "p99_ms": round(self.p99_ms, 3),
            "max_ms": round(self.max_ms, 3),
        }


def aggregate(
    samples: Iterable[LatencySample],
    *,
    window: str = "1H",
    tz: str = "UTC",
) -> List[LatencyRollup]:
    """Aggregate latency samples into fixed windows.

    Parameters
    ----------
    samples:
        Iterable of :class:`LatencySample` items. Items are sorted by timestamp
        prior to aggregation.
    window:
        Window definition expressed as ``<int><unit>``. Only hour (``H``) and
        minute (``M``) granularity are currently supported.
    tz:
        Target timezone for rollup boundaries. ``UTC`` by default.
    """

    tzinfo = _tzinfo_from_name(tz)
    window_delta = _parse_window(window)
    normalised: List[LatencySample] = [
        LatencySample(
            timestamp=_ensure_timezone(sample.timestamp, tzinfo),
            latency_ms=float(sample.latency_ms),
            status=sample.status,
            detail=sample.detail,
            source=sample.source,
        )
        for sample in samples
    ]
    normalised.sort(key=lambda item: item.timestamp)
    rollups: List[LatencyRollup] = []
    for window_start, bucket in _bucketise(normalised, window_delta, tzinfo):
        latencies = [entry.latency_ms for entry in bucket]
        failure_count = sum(1 for entry in bucket if entry.is_failure())
        rollups.append(
            LatencyRollup(
                window_start=window_start,
                window_end=window_start + window_delta,
                count=len(bucket),
                failure_count=failure_count,
                p50_ms=_percentile(latencies, 50.0),
                p95_ms=_percentile(latencies, 95.0),
                p99_ms=_percentile(latencies, 99.0),
                max_ms=max(latencies) if latencies else 0.0,
            )
        )
    return rollups


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    k = (len(ordered) - 1) * (percentile / 100.0)
    lower = int(k)
    upper = min(lower + 1, len(ordered) - 1)
    weight = k - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _bucketise(
    samples: Sequence[LatencySample],
    window: timedelta,
    tzinfo: timezone,
) -> Iterator[tuple[datetime, List[LatencySample]]]:
    if not samples:
        return
    bucket: List[LatencySample] = []
    current_start = _floor_timestamp(samples[0].timestamp, window, tzinfo)
    for sample in samples:
        sample_start = _floor_timestamp(sample.timestamp, window, tzinfo)
        if sample_start != current_start:
            yield current_start, bucket
            bucket = []
            current_start = sample_start
        bucket.append(sample)
    if bucket:
        yield current_start, bucket


def _floor_timestamp(
    value: datetime,
    window: timedelta,
    tzinfo: timezone,
) -> datetime:
    aware = _ensure_timezone(value, tzinfo)
    epoch_seconds = int(aware.timestamp())
    window_seconds = int(window.total_seconds())
    floored = epoch_seconds - (epoch_seconds % window_seconds)
    return datetime.fromtimestamp(floored, tz=tzinfo)


def _parse_window(window: str) -> timedelta:
    if not window:
        raise ValueError("window must be non-empty")
    unit = window[-1].upper()
    try:
        value = int(window[:-1])
    except ValueError as exc:  # pragma: no cover - defensive
        raise ValueError(f"Invalid window specification: {window}") from exc
    if value <= 0:
        raise ValueError("window value must be positive")
    if unit == "H":
        return timedelta(hours=value)
    if unit == "M":
        return timedelta(minutes=value)
    raise ValueError(f"Unsupported window unit: {unit}")


def _ensure_timezone(value: datetime, tzinfo: timezone) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=tzinfo)
    return value.astimezone(tzinfo)


def _tzinfo_from_name(name: str) -> timezone:
    normalized = (name or "UTC").upper()
    if normalized != "UTC":
        raise ValueError("Only UTC timezone is currently supported")
    return timezone.utc


def _format_ts(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
