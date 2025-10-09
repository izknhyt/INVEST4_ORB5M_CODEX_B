from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

import pytest

from scripts import check_data_quality


def _write_sample_csv(path: Path) -> None:
    rows = [
        "timestamp,symbol,tf,o,h,l,c,v,spread",
        "2024-01-01T00:00:00Z,USDJPY,5m,144.0,144.5,143.8,144.2,100,0.5",
        "2024-01-01 00:05:00,USDJPY,5m,144.2,144.7,144.1,144.4,120,0.5",
        "2024-01-01T00:15:00+00:00,USDJPY,5m,144.4,144.8,144.3,144.6,90,0.6",
        "2024-01-01T00:15:00+00:00,USDJPY,5m,144.4,144.9,144.3,144.6,95,0.6",
        "2024-01-01T00:20:00Z,USDJPY,5m,144.6,145.0,144.5,144.8,110,0.6",
    ]
    path.write_text("\n".join(rows), encoding="utf-8")


def test_audit_summarises_gaps_and_coverage(tmp_path):
    csv_path = tmp_path / "sample.csv"
    _write_sample_csv(csv_path)

    summary = check_data_quality.audit(csv_path)

    assert summary["row_count"] == 5
    assert summary["unique_timestamps"] == 4
    assert summary["duplicates"] == 1
    assert summary["gap_count"] == 1
    assert summary["max_gap_minutes"] == pytest.approx(10.0)
    assert summary["total_gap_minutes"] == pytest.approx(10.0)
    assert summary["average_gap_minutes"] == pytest.approx(10.0)
    assert summary["missing_rows_estimate"] == 1
    assert summary["irregular_gap_count"] == 0
    assert summary["start_timestamp"] == "2024-01-01T00:00:00"
    assert summary["end_timestamp"] == "2024-01-01T00:20:00"
    assert summary["expected_rows"] == 5
    assert summary["coverage_ratio"] == pytest.approx(0.8)
    assert summary["gaps"][0][2] == pytest.approx(10.0)
    assert summary["gap_details"][0]["missing_rows_estimate"] == 1
    assert summary["expected_interval_minutes"] == pytest.approx(5.0)
    assert summary["expected_interval_source"] in {"tf_column", "observed_diff"}


def test_main_writes_json_summary(tmp_path, capsys):
    csv_path = tmp_path / "sample.csv"
    _write_sample_csv(csv_path)

    out_path = tmp_path / "summary.json"
    rc = check_data_quality.main([
        "--csv",
        str(csv_path),
        "--out-json",
        str(out_path),
        "--max-gap-report",
        "5",
    ])

    assert rc == 0
    captured = capsys.readouterr()
    assert "row_count" in captured.out

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["row_count"] == 5
    assert payload["max_gap_minutes"] == pytest.approx(10.0)
    assert payload["gap_details"][0]["gap_minutes"] == pytest.approx(10.0)
    assert payload["missing_rows_estimate"] == 1
    assert payload["expected_interval_minutes"] == pytest.approx(5.0)
    assert payload["expected_interval_source"] in {"tf_column", "observed_diff"}


def test_main_writes_gap_csv(tmp_path, capsys):
    csv_path = tmp_path / "sample.csv"
    _write_sample_csv(csv_path)

    gap_out = tmp_path / "gaps.csv"
    rc = check_data_quality.main([
        "--csv",
        str(csv_path),
        "--out-gap-csv",
        str(gap_out),
        "--max-gap-report",
        "3",
    ])

    assert rc == 0
    capsys.readouterr()
    rows = list(csv.DictReader(gap_out.open(encoding="utf-8")))
    assert len(rows) == 1
    assert rows[0]["start_timestamp"] == "2024-01-01T00:05:00"
    assert rows[0]["end_timestamp"] == "2024-01-01T00:15:00"
    assert rows[0]["missing_rows_estimate"] == "1"


def test_main_rejects_inverted_time_window(tmp_path):
    csv_path = tmp_path / "sample.csv"
    _write_sample_csv(csv_path)

    with pytest.raises(SystemExit) as excinfo:
        check_data_quality.main([
            "--csv",
            str(csv_path),
            "--start-timestamp",
            "2024-01-02T00:00:00Z",
            "--end-timestamp",
            "2024-01-01T00:00:00Z",
        ])

    assert "must be earlier" in str(excinfo.value)


def test_expected_interval_detection_and_override(tmp_path):
    csv_path = tmp_path / "sample_15m.csv"
    csv_path.write_text(
        "\n".join(
            [
                "timestamp,symbol,tf,o,h,l,c,v,spread",
                "2024-01-01T00:00:00Z,USDJPY,15m,144.0,144.5,143.8,144.2,100,0.5",
                "2024-01-01T00:15:00Z,USDJPY,15m,144.2,144.7,144.1,144.4,120,0.5",
                "2024-01-01T00:45:00Z,USDJPY,15m,144.4,144.8,144.3,144.6,90,0.6",
            ]
        ),
        encoding="utf-8",
    )

    summary = check_data_quality.audit(csv_path)
    assert summary["expected_interval_minutes"] == pytest.approx(15.0)
    assert summary["expected_interval_source"] in {"tf_column", "observed_diff"}
    assert summary["missing_rows_estimate"] == 1
    assert summary["gap_count"] == 1

    overridden = check_data_quality.audit(
        csv_path, expected_interval_minutes=10.0
    )
    assert overridden["expected_interval_minutes"] == pytest.approx(10.0)
    # 15 minute and 30 minute gaps against a 10 minute baseline imply three missing rows in total.
    assert overridden["missing_rows_estimate"] == 3
    assert overridden["gap_count"] == 2
    assert overridden["expected_interval_source"] == "override"


def test_time_window_filters_limit_analysis(tmp_path):
    csv_path = tmp_path / "sample.csv"
    _write_sample_csv(csv_path)

    summary = check_data_quality.audit(
        csv_path,
        start_timestamp=datetime.fromisoformat("2024-01-01T00:05:00"),
        end_timestamp=datetime.fromisoformat("2024-01-01T00:15:00"),
    )

    assert summary["start_timestamp"] == "2024-01-01T00:05:00"
    assert summary["end_timestamp"] == "2024-01-01T00:15:00"
    assert summary["row_count"] == 3
    assert summary["unique_timestamps"] == 2
    assert summary["duplicates"] == 1
    assert summary["gap_count"] == 1
    assert summary["missing_rows_estimate"] == 1
    assert summary["start_timestamp_filter"] == "2024-01-01T00:05:00"
    assert summary["end_timestamp_filter"] == "2024-01-01T00:15:00"
