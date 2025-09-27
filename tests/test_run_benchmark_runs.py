"""Tests for scripts.run_benchmark_runs utilities."""
from __future__ import annotations

from scripts.run_benchmark_runs import _filter_window


def test_filter_window_handles_mixed_timestamp_formats() -> None:
    rows = [
        {"timestamp": "2024-01-01T00:00:00Z", "label": "z"},
        {"timestamp": "2024-01-02 00:00:00", "label": "space"},
        {"timestamp": "2024-01-03T12:34:56.789Z", "label": "fractional"},
        {"timestamp": "2024-01-04T09:00:00+09:00", "label": "offset"},
    ]

    filtered = _filter_window(rows, days=2)

    assert filtered == rows[1:]
