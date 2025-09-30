from datetime import datetime, timezone

from scripts.analyze_signal_latency import parse_iso


def test_parse_iso_handles_z_suffix():
    ts = parse_iso("2024-01-01T12:34:56Z")
    assert ts == datetime(2024, 1, 1, 12, 34, 56, tzinfo=timezone.utc)


def test_parse_iso_handles_space_separator():
    ts = parse_iso("2024-01-01 12:34:56Z")
    assert ts == datetime(2024, 1, 1, 12, 34, 56, tzinfo=timezone.utc)
