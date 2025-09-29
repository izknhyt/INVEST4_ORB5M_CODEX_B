import datetime as dt
import json
from pathlib import Path

import pytest

from scripts.check_benchmark_freshness import check_benchmark_freshness, main


@pytest.fixture
def fixed_now() -> dt.datetime:
    return dt.datetime(2025, 1, 1, 12, 0, tzinfo=dt.timezone.utc)


@pytest.fixture
def snapshot_dir(tmp_path: Path):
    def _create_snapshot(data: dict) -> Path:
        path = tmp_path / "runtime_snapshot.json"
        path.write_text(json.dumps(data, indent=2))
        return path

    return _create_snapshot


@pytest.fixture
def fresh_snapshot(snapshot_dir, fixed_now: dt.datetime) -> Path:
    base_ts = (fixed_now - dt.timedelta(hours=1)).isoformat()
    summary_ts = (fixed_now - dt.timedelta(minutes=20)).isoformat().replace(
        "+00:00", "Z"
    )
    data = {
        "benchmarks": {"USDJPY_conservative": base_ts},
        "benchmark_pipeline": {
            "USDJPY_conservative": {
                "latest_ts": base_ts,
                "summary_generated_at": summary_ts,
            }
        },
    }
    return snapshot_dir(data)


@pytest.fixture
def stale_snapshot(snapshot_dir, fixed_now: dt.datetime) -> Path:
    base_ts = (fixed_now - dt.timedelta(hours=10)).isoformat()
    summary_ts = (fixed_now - dt.timedelta(hours=9)).isoformat()
    data = {
        "benchmarks": {"USDJPY_conservative": base_ts},
        "benchmark_pipeline": {
            "USDJPY_conservative": {
                "latest_ts": base_ts,
                "summary_generated_at": summary_ts,
            }
        },
    }
    return snapshot_dir(data)


@pytest.fixture
def missing_fields_snapshot(snapshot_dir) -> Path:
    data = {
        "benchmarks": {},
        "benchmark_pipeline": {
            "USDJPY_conservative": {
                "latest_ts": None,
            }
        },
    }
    return snapshot_dir(data)


def test_check_benchmark_freshness_ok(fresh_snapshot: Path, fixed_now: dt.datetime):
    result = check_benchmark_freshness(
        snapshot_path=fresh_snapshot,
        targets=["USDJPY:conservative"],
        max_age_hours=6,
        now=fixed_now,
    )
    assert result["ok"] is True
    assert result["errors"] == []
    checked = result["checked"][0]
    assert checked["benchmarks_timestamp"].startswith("2025-01-01T11:00:00")
    assert checked["summary_generated_at"].endswith("Z")


def test_check_benchmark_freshness_reports_stale(
    stale_snapshot: Path, fixed_now: dt.datetime
):
    result = check_benchmark_freshness(
        snapshot_path=stale_snapshot,
        targets=["USDJPY_conservative"],
        max_age_hours=6,
        now=fixed_now,
    )
    assert result["ok"] is False
    assert any("stale" in err for err in result["errors"])


def test_cli_missing_fields_outputs_errors(missing_fields_snapshot: Path, capsys):
    exit_code = main(
        [
            "--snapshot",
            str(missing_fields_snapshot),
            "--target",
            "USDJPY:conservative",
            "--max-age-hours",
            "6",
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 1
    assert payload["ok"] is False
    assert "benchmarks.USDJPY_conservative missing" in payload["errors"]
