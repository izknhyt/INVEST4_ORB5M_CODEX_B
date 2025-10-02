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


@pytest.fixture
def synthetic_snapshot(snapshot_dir, fixed_now: dt.datetime) -> Path:
    base_ts = (fixed_now - dt.timedelta(hours=12)).isoformat()
    summary_ts = (fixed_now - dt.timedelta(hours=11)).isoformat()
    data = {
        "benchmarks": {"USDJPY_conservative": base_ts},
        "benchmark_pipeline": {
            "USDJPY_conservative": {
                "latest_ts": base_ts,
                "summary_generated_at": summary_ts,
            }
        },
        "ingest_meta": {
            "USDJPY_5m": {
                "synthetic_extension": True,
                "primary_source": "local_csv",
                "freshness_minutes": 130.5,
                "fallbacks": ["local_csv", "synthetic_local"],
                "source_chain": [
                    {"source": "local_csv"},
                    {"source": "synthetic_local"},
                ],
                "last_ingest_at": "2025-01-01T10:15:00+00:00",
                "local_backup_path": "/data/usdjpy_5m_2018-2024_utc.csv",
            }
        },
    }
    return snapshot_dir(data)


@pytest.fixture
def synthetic_missing_pipeline_snapshot(
    snapshot_dir, fixed_now: dt.datetime
) -> Path:
    base_ts = (fixed_now - dt.timedelta(hours=12)).isoformat()
    data = {
        "benchmarks": {"USDJPY_conservative": base_ts},
        "benchmark_pipeline": {},
        "ingest_meta": {
            "USDJPY_5m": {
                "synthetic_extension": True,
                "primary_source": "local_csv",
                "freshness_minutes": 180.0,
                "source_chain": [
                    {"source": "local_csv"},
                    {"source": "synthetic_local"},
                ],
                "fallbacks": [
                    {"stage": "dukascopy", "reason": "dependency_missing"},
                    {"stage": "yfinance", "reason": "dependency_missing"},
                ],
                "last_ingest_at": "2025-01-01T08:15:00+00:00",
            }
        },
    }
    return snapshot_dir(data)


@pytest.fixture
def synthetic_missing_benchmarks_snapshot(
    snapshot_dir, fixed_now: dt.datetime
) -> Path:
    base_ts = (fixed_now - dt.timedelta(minutes=10)).isoformat()
    summary_ts = (fixed_now - dt.timedelta(minutes=5)).isoformat()
    data = {
        "benchmarks": {},
        "benchmark_pipeline": {
            "USDJPY_conservative": {
                "latest_ts": base_ts,
                "summary_generated_at": summary_ts,
            }
        },
        "ingest_meta": {
            "USDJPY_5m": {
                "synthetic_extension": True,
                "primary_source": "local_csv",
                "source_chain": [
                    {"source": "local_csv"},
                    {"source": "synthetic_local"},
                ],
                "fallbacks": ["local_csv", "synthetic_local"],
                "freshness_minutes": 55.0,
                "last_ingest_at": "2025-01-01T11:05:00+00:00",
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
    assert result["advisories"] == []
    assert result["benchmark_max_age_hours"] == pytest.approx(6)
    checked = result["checked"][0]
    assert checked["benchmarks_timestamp"].startswith("2025-01-01T11:00:00")
    assert checked["summary_generated_at"].endswith("Z")
    assert checked["advisories"] == []


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
    checked = result["checked"][0]
    assert checked["advisories"] == []


def test_stale_with_synthetic_is_advisory(
    synthetic_snapshot: Path, fixed_now: dt.datetime
):
    result = check_benchmark_freshness(
        snapshot_path=synthetic_snapshot,
        targets=["USDJPY:conservative"],
        max_age_hours=6,
        now=fixed_now,
    )

    assert result["ok"] is True
    assert result["errors"] == []
    assert result["advisories"]
    checked = result["checked"][0]
    assert checked["errors"] == []
    assert checked["advisories"]
    ingest_meta = checked.get("ingest_metadata")
    assert ingest_meta is not None
    assert ingest_meta["synthetic_extension"] is True
    assert ingest_meta["primary_source"] == "local_csv"
    assert ingest_meta["freshness_minutes"] == pytest.approx(130.5)
    assert ingest_meta["fallbacks"] == ["local_csv", "synthetic_local"]
    assert ingest_meta["source_chain"] == ["local_csv", "synthetic_local"]
    assert ingest_meta["last_ingest_at"].startswith("2025-01-01T10:15:00")
    assert (
        ingest_meta["local_backup_path"]
        == "/data/usdjpy_5m_2018-2024_utc.csv"
    )


def test_missing_pipeline_with_synthetic_is_advisory(
    synthetic_missing_pipeline_snapshot: Path, fixed_now: dt.datetime
):
    result = check_benchmark_freshness(
        snapshot_path=synthetic_missing_pipeline_snapshot,
        targets=["USDJPY:conservative"],
        max_age_hours=6,
        now=fixed_now,
    )

    assert result["ok"] is True
    assert result["errors"] == []
    assert result["advisories"]
    assert any(
        msg.startswith("benchmark_pipeline.") for msg in result["advisories"]
    )
    checked = result["checked"][0]
    metadata = checked.get("ingest_metadata")
    assert metadata is not None
    assert metadata.get("fallbacks") == ["dukascopy", "yfinance"]


def test_benchmarks_missing_with_synthetic_is_advisory(
    synthetic_missing_benchmarks_snapshot: Path, fixed_now: dt.datetime
):
    result = check_benchmark_freshness(
        snapshot_path=synthetic_missing_benchmarks_snapshot,
        targets=["USDJPY:conservative"],
        max_age_hours=6,
        now=fixed_now,
    )

    assert result["ok"] is True
    assert result["errors"] == []
    assert any(
        msg.startswith("benchmarks.") for msg in result["advisories"]
    )
    checked = result["checked"][0]
    assert checked["errors"] == []
    assert any(
        msg.startswith("benchmarks.") for msg in checked["advisories"]
    )


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
    assert "advisories" in payload


def test_benchmark_specific_threshold(fresh_snapshot: Path, fixed_now: dt.datetime):
    result = check_benchmark_freshness(
        snapshot_path=fresh_snapshot,
        targets=["USDJPY:conservative"],
        max_age_hours=6,
        benchmark_max_age_hours=0.5,
        now=fixed_now,
    )

    assert result["ok"] is False
    assert any(
        msg.startswith("benchmarks.") and "limit 0.5" in msg for msg in result["errors"]
    )
    checked = result["checked"][0]
    assert checked["benchmarks_age_hours"] == pytest.approx(1.0)
    assert any(
        msg.startswith("benchmarks.") and "limit 0.5" in msg for msg in checked["errors"]
    )
    assert not any(
        msg.startswith("benchmark_pipeline.") for msg in checked.get("errors", [])
    )


def test_cli_accepts_benchmark_specific_threshold(
    fresh_snapshot: Path, capsys
):
    exit_code = main(
        [
            "--snapshot",
            str(fresh_snapshot),
            "--target",
            "USDJPY:conservative",
            "--max-age-hours",
            "6",
            "--benchmark-freshness-max-age-hours",
            "0.5",
        ]
    )
    output = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert output["benchmark_max_age_hours"] == pytest.approx(0.5)
    assert any(
        msg.startswith("benchmarks.") and "limit 0.5" in msg for msg in output["errors"]
    )
