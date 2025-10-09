from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import check_data_quality


def _write_sample_csv(path: Path) -> None:
    rows = [
        "timestamp,symbol,tf,o,h,l,c,v,spread",
        "2024-01-01T00:00:00,USDJPY,5m,144.0,144.5,143.8,144.2,100,0.5",
        "2024-01-01T00:05:00,USDJPY,5m,144.2,144.7,144.1,144.4,120,0.5",
        "2024-01-01T00:15:00,USDJPY,5m,144.4,144.8,144.3,144.6,90,0.6",
        "2024-01-01T00:15:00,USDJPY,5m,144.4,144.9,144.3,144.6,95,0.6",
        "2024-01-01T00:20:00,USDJPY,5m,144.6,145.0,144.5,144.8,110,0.6",
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
    assert summary["start_timestamp"] == "2024-01-01T00:00:00"
    assert summary["end_timestamp"] == "2024-01-01T00:20:00"
    assert summary["expected_rows"] == 5
    assert summary["coverage_ratio"] == pytest.approx(0.8)


def test_main_writes_json_summary(tmp_path, capsys):
    csv_path = tmp_path / "sample.csv"
    _write_sample_csv(csv_path)

    out_path = tmp_path / "summary.json"
    rc = check_data_quality.main([
        "--csv",
        str(csv_path),
        "--out-json",
        str(out_path),
    ])

    assert rc == 0
    captured = capsys.readouterr()
    assert "row_count" in captured.out

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["row_count"] == 5
    assert payload["max_gap_minutes"] == pytest.approx(10.0)
