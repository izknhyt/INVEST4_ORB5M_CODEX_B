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


def _write_multi_day_csv(path: Path) -> None:
    rows = [
        "timestamp,symbol,tf,o,h,l,c,v,spread",
        "2024-01-01T00:00:00Z,USDJPY,5m,1,1,1,1,0,0",
        "2024-01-01T00:05:00Z,USDJPY,5m,1,1,1,1,0,0",
        "2024-01-01T00:10:00Z,USDJPY,5m,1,1,1,1,0,0",
        "2024-01-02T00:00:00Z,USDJPY,5m,1,1,1,1,0,0",
        "2024-01-02T00:05:00Z,USDJPY,5m,1,1,1,1,0,0",
        "2024-01-02T00:15:00Z,USDJPY,5m,1,1,1,1,0,0",
    ]
    path.write_text("\n".join(rows), encoding="utf-8")


def test_audit_summarises_gaps_and_coverage(tmp_path):
    csv_path = tmp_path / "sample.csv"
    _write_sample_csv(csv_path)

    summary = check_data_quality.audit(csv_path)

    assert summary["row_count"] == 5
    assert summary["unique_timestamps"] == 4
    assert summary["duplicates"] == 1
    assert summary["duplicate_groups"] == 1
    assert summary["duplicate_details_truncated"] is False
    assert summary["duplicate_details"] == [
        {
            "timestamp": "2024-01-01T00:15:00",
            "occurrences": 2,
            "line_numbers": [4, 5],
        }
    ]
    assert summary["duplicate_max_occurrences"] == 2
    assert summary["duplicate_first_timestamp"] == "2024-01-01T00:15:00"
    assert summary["duplicate_last_timestamp"] == "2024-01-01T00:15:00"
    assert summary["duplicate_timestamp_span_minutes"] == pytest.approx(0.0)
    assert summary["duplicate_min_occurrences"] == 2
    assert summary["ignored_duplicate_groups"] == 0
    assert summary["ignored_duplicate_rows"] == 0
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
    assert summary["min_gap_minutes"] == pytest.approx(0.0)
    assert summary["ignored_gap_count"] == 0
    assert summary["ignored_gap_minutes"] == pytest.approx(0.0)
    assert summary["ignored_missing_rows_estimate"] == 0


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
    assert payload["ignored_gap_count"] == 0
    assert payload["duplicate_groups"] == 1
    assert payload["duplicate_details_truncated"] is False
    assert payload["duplicate_min_occurrences"] == 2
    assert payload["ignored_duplicate_groups"] == 0
    assert payload["ignored_duplicate_rows"] == 0


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


def test_main_writes_gap_json(tmp_path, capsys):
    csv_path = tmp_path / "sample.csv"
    _write_sample_csv(csv_path)

    gap_json = tmp_path / "gaps.json"
    rc = check_data_quality.main([
        "--csv",
        str(csv_path),
        "--out-gap-json",
        str(gap_json),
    ])

    assert rc == 0
    capsys.readouterr()
    gap_payload = json.loads(gap_json.read_text(encoding="utf-8"))
    assert len(gap_payload) == 1
    assert gap_payload[0]["gap_minutes"] == pytest.approx(10.0)


def test_main_writes_duplicate_exports(tmp_path, capsys):
    csv_path = tmp_path / "sample.csv"
    _write_sample_csv(csv_path)

    dup_csv = tmp_path / "dups.csv"
    dup_json = tmp_path / "dups.json"
    rc = check_data_quality.main(
        [
            "--csv",
            str(csv_path),
            "--out-duplicates-csv",
            str(dup_csv),
            "--out-duplicates-json",
            str(dup_json),
        ]
    )

    assert rc == 0
    capsys.readouterr()
    dup_rows = list(csv.DictReader(dup_csv.open(encoding="utf-8")))
    assert dup_rows == [
        {
            "timestamp": "2024-01-01T00:15:00",
            "occurrences": "2",
            "line_numbers": "4,5",
        }
    ]
    dup_payload = json.loads(dup_json.read_text(encoding="utf-8"))
    assert dup_payload == [
        {
            "timestamp": "2024-01-01T00:15:00",
            "occurrences": 2,
            "line_numbers": [4, 5],
        }
    ]


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
    assert overridden["ignored_gap_count"] == 0


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
    assert summary["ignored_gap_count"] == 0


def test_min_gap_filtering_excludes_small_gaps(tmp_path):
    csv_path = tmp_path / "sample.csv"
    _write_sample_csv(csv_path)

    summary = check_data_quality.audit(csv_path, min_gap_minutes=12.0)

    assert summary["gap_count"] == 0
    assert summary["ignored_gap_count"] == 1
    assert summary["ignored_gap_minutes"] == pytest.approx(10.0)
    assert summary["ignored_missing_rows_estimate"] == 1
    assert summary["missing_rows_estimate"] == 0
    assert summary["ignored_duplicate_groups"] == 0
    assert summary["ignored_duplicate_rows"] == 0


def test_main_rejects_negative_min_gap(tmp_path):
    csv_path = tmp_path / "sample.csv"
    _write_sample_csv(csv_path)

    with pytest.raises(SystemExit) as excinfo:
        check_data_quality.main([
            "--csv",
            str(csv_path),
            "--min-gap-minutes",
            "-1",
        ])

    assert "non-negative" in str(excinfo.value)


def test_main_rejects_invalid_min_duplicate_occurrences(tmp_path):
    csv_path = tmp_path / "sample.csv"
    _write_sample_csv(csv_path)

    with pytest.raises(SystemExit) as excinfo:
        check_data_quality.main([
            "--csv",
            str(csv_path),
            "--min-duplicate-occurrences",
            "1",
        ])

    assert "at least 2" in str(excinfo.value)


def test_duplicate_report_truncation(tmp_path):
    csv_path = tmp_path / "dups.csv"
    rows = [
        "timestamp,symbol,tf,o,h,l,c,v,spread",
        "2024-01-01T00:00:00Z,USDJPY,5m,1,1,1,1,0,0",
        "2024-01-01T00:00:00Z,USDJPY,5m,1,1,1,1,0,0",
        "2024-01-01T00:05:00Z,USDJPY,5m,1,1,1,1,0,0",
        "2024-01-01T00:05:00Z,USDJPY,5m,1,1,1,1,0,0",
        "2024-01-01T00:10:00Z,USDJPY,5m,1,1,1,1,0,0",
        "2024-01-01T00:10:00Z,USDJPY,5m,1,1,1,1,0,0",
    ]
    csv_path.write_text("\n".join(rows), encoding="utf-8")

    summary = check_data_quality.audit(csv_path, max_duplicate_report=1)

    assert summary["duplicates"] == 3
    assert summary["duplicate_groups"] == 3
    assert len(summary["duplicate_details"]) == 1
    assert summary["duplicate_details_truncated"] is True
    assert summary["duplicate_max_occurrences"] == 2
    assert summary["duplicate_first_timestamp"] == "2024-01-01T00:00:00"
    assert summary["duplicate_last_timestamp"] == "2024-01-01T00:10:00"
    assert summary["duplicate_timestamp_span_minutes"] == pytest.approx(10.0)
    assert summary["duplicate_min_occurrences"] == 2
    assert summary["ignored_duplicate_groups"] == 0
    assert summary["ignored_duplicate_rows"] == 0


def test_duplicate_details_prioritise_high_occurrence(tmp_path):
    csv_path = tmp_path / "dups_weighted.csv"
    rows = [
        "timestamp,symbol,tf,o,h,l,c,v,spread",
        "2024-01-01T00:00:00Z,USDJPY,5m,1,1,1,1,0,0",
        "2024-01-01T00:00:00Z,USDJPY,5m,1,1,1,1,0,0",
        "2024-01-01T00:05:00Z,USDJPY,5m,1,1,1,1,0,0",
        "2024-01-01T00:05:00Z,USDJPY,5m,1,1,1,1,0,0",
        "2024-01-01T00:05:00Z,USDJPY,5m,1,1,1,1,0,0",
        "2024-01-01T00:10:00Z,USDJPY,5m,1,1,1,1,0,0",
    ]
    csv_path.write_text("\n".join(rows), encoding="utf-8")

    summary = check_data_quality.audit(csv_path, max_duplicate_report=2)

    assert [item["timestamp"] for item in summary["duplicate_details"]] == [
        "2024-01-01T00:05:00",
        "2024-01-01T00:00:00",
    ]
    assert summary["duplicate_details"][0]["occurrences"] == 3
    assert summary["duplicate_details"][1]["occurrences"] == 2
    assert summary["duplicate_max_occurrences"] == 3
    assert summary["ignored_duplicate_groups"] == 0
    assert summary["ignored_duplicate_rows"] == 0


def test_min_duplicate_occurrences_filters_summary_and_exports(tmp_path, capsys):
    csv_path = tmp_path / "dups_filtered.csv"
    rows = [
        "timestamp,symbol,tf,o,h,l,c,v,spread",
        "2024-01-01T00:00:00Z,USDJPY,5m,1,1,1,1,0,0",
        "2024-01-01T00:00:00Z,USDJPY,5m,1,1,1,1,0,0",
        "2024-01-01T00:05:00Z,USDJPY,5m,1,1,1,1,0,0",
        "2024-01-01T00:05:00Z,USDJPY,5m,1,1,1,1,0,0",
        "2024-01-01T00:05:00Z,USDJPY,5m,1,1,1,1,0,0",
        "2024-01-01T00:10:00Z,USDJPY,5m,1,1,1,1,0,0",
        "2024-01-01T00:10:00Z,USDJPY,5m,1,1,1,1,0,0",
    ]
    csv_path.write_text("\n".join(rows), encoding="utf-8")

    summary = check_data_quality.audit(
        csv_path,
        min_duplicate_occurrences=3,
    )

    assert summary["duplicate_groups"] == 1
    assert summary["duplicates"] == 2
    assert [item["timestamp"] for item in summary["duplicate_details"]] == [
        "2024-01-01T00:05:00",
    ]
    assert summary["duplicate_min_occurrences"] == 3
    assert summary["ignored_duplicate_groups"] == 2
    assert summary["ignored_duplicate_rows"] == 2

    dup_csv = tmp_path / "dups_filtered.csv.out"
    dup_json = tmp_path / "dups_filtered.json"
    rc = check_data_quality.main(
        [
            "--csv",
            str(csv_path),
            "--min-duplicate-occurrences",
            "3",
            "--out-duplicates-csv",
            str(dup_csv),
            "--out-duplicates-json",
            str(dup_json),
        ]
    )

    assert rc == 0
    capsys.readouterr()
    dup_rows = list(csv.DictReader(dup_csv.open(encoding="utf-8")))
    assert dup_rows == [
        {
            "timestamp": "2024-01-01T00:05:00",
            "occurrences": "3",
            "line_numbers": "4,5,6",
        }
    ]
    dup_payload = json.loads(dup_json.read_text(encoding="utf-8"))
    assert dup_payload == [
        {
            "timestamp": "2024-01-01T00:05:00",
            "occurrences": 3,
            "line_numbers": [4, 5, 6],
        }
    ]


def test_calendar_day_summary_highlights_low_coverage(tmp_path):
    csv_path = tmp_path / "multi_day.csv"
    _write_multi_day_csv(csv_path)

    summary = check_data_quality.audit(
        csv_path,
        calendar_day_summary=True,
        calendar_day_max_report=5,
        calendar_day_coverage_threshold=0.95,
    )

    calendar = summary["calendar_day_summary"]
    assert calendar["count"] == 2
    assert calendar["coverage_threshold"] == pytest.approx(0.95)
    assert calendar["expected_rows_per_day"] == 288
    # Worst coverage day should be surfaced first.
    assert calendar["details"][0]["date"] == "2024-01-02"
    assert calendar["details"][0]["coverage_ratio"] == pytest.approx(0.75)
    assert calendar["details"][0]["missing_rows_estimate"] == 1
    assert calendar["details"][0]["gap_count"] == 1
    assert calendar["warnings"][0]["date"] == "2024-01-02"
    assert calendar["warnings"][0]["coverage_ratio"] == pytest.approx(0.75)


def test_main_supports_calendar_day_summary(tmp_path, capsys):
    csv_path = tmp_path / "multi_day.csv"
    _write_multi_day_csv(csv_path)
    out_path = tmp_path / "summary.json"

    rc = check_data_quality.main(
        [
            "--csv",
            str(csv_path),
            "--out-json",
            str(out_path),
            "--calendar-day-summary",
            "--calendar-day-max-report",
            "2",
            "--calendar-day-coverage-threshold",
            "0.9",
        ]
    )

    assert rc == 0
    capsys.readouterr()
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    calendar = payload["calendar_day_summary"]
    assert calendar["details"][0]["date"] == "2024-01-02"
    assert calendar["warnings"][0]["date"] == "2024-01-02"
    assert calendar["coverage_threshold"] == pytest.approx(0.9)


def test_main_fails_when_coverage_below_threshold(tmp_path, capsys):
    csv_path = tmp_path / "sample.csv"
    _write_sample_csv(csv_path)

    rc = check_data_quality.main(
        [
            "--csv",
            str(csv_path),
            "--fail-under-coverage",
            "0.9",
        ]
    )

    assert rc == 1
    captured = capsys.readouterr()
    assert "coverage_ratio" in captured.err
    assert "FAILURE" in captured.err


def test_main_fails_when_duplicate_groups_reach_threshold(tmp_path, capsys):
    csv_path = tmp_path / "sample.csv"
    _write_sample_csv(csv_path)

    rc = check_data_quality.main(
        [
            "--csv",
            str(csv_path),
            "--fail-on-duplicate-groups",
            "1",
        ]
    )

    assert rc == 1
    captured = capsys.readouterr()
    assert "duplicate_groups" in captured.err


def test_main_fails_when_duplicate_occurrences_reach_threshold(tmp_path, capsys):
    csv_path = tmp_path / "sample.csv"
    _write_sample_csv(csv_path)

    rc = check_data_quality.main(
        [
            "--csv",
            str(csv_path),
            "--fail-on-duplicate-occurrences",
            "2",
        ]
    )

    assert rc == 1
    captured = capsys.readouterr()
    assert "duplicate_max_occurrences" in captured.err


def test_main_allows_duplicate_threshold_zero(tmp_path, capsys):
    csv_path = tmp_path / "sample.csv"
    _write_sample_csv(csv_path)

    rc = check_data_quality.main(
        [
            "--csv",
            str(csv_path),
            "--fail-on-duplicate-groups",
            "0",
        ]
    )

    assert rc == 0
    captured = capsys.readouterr()
    assert "FAILURE" not in captured.err


def test_main_allows_duplicate_occurrence_threshold_zero(tmp_path, capsys):
    csv_path = tmp_path / "sample.csv"
    _write_sample_csv(csv_path)

    rc = check_data_quality.main(
        [
            "--csv",
            str(csv_path),
            "--fail-on-duplicate-occurrences",
            "0",
        ]
    )

    assert rc == 0
    captured = capsys.readouterr()
    assert "duplicate_max_occurrences" not in captured.err


def test_main_rejects_negative_duplicate_group_threshold(tmp_path):
    csv_path = tmp_path / "sample.csv"
    _write_sample_csv(csv_path)

    with pytest.raises(SystemExit) as excinfo:
        check_data_quality.main(
            [
                "--csv",
                str(csv_path),
                "--fail-on-duplicate-groups",
                "-1",
            ]
        )

    assert "at least 0" in str(excinfo.value)


def test_main_rejects_negative_duplicate_occurrence_threshold(tmp_path):
    csv_path = tmp_path / "sample.csv"
    _write_sample_csv(csv_path)

    with pytest.raises(SystemExit) as excinfo:
        check_data_quality.main(
            [
                "--csv",
                str(csv_path),
                "--fail-on-duplicate-occurrences",
                "-1",
            ]
        )

    assert "at least 0" in str(excinfo.value)


def test_main_requires_calendar_summary_for_warning_failures(tmp_path):
    csv_path = tmp_path / "sample.csv"
    _write_sample_csv(csv_path)

    with pytest.raises(SystemExit) as excinfo:
        check_data_quality.main(
            [
                "--csv",
                str(csv_path),
                "--fail-on-calendar-day-warnings",
            ]
        )

    assert "requires --calendar-day-summary" in str(excinfo.value)


def test_main_fails_when_calendar_day_warnings_present(tmp_path, capsys):
    csv_path = tmp_path / "multi_day.csv"
    _write_multi_day_csv(csv_path)

    rc = check_data_quality.main(
        [
            "--csv",
            str(csv_path),
            "--calendar-day-summary",
            "--calendar-day-coverage-threshold",
            "0.9",
            "--fail-on-calendar-day-warnings",
        ]
    )

    assert rc == 1
    captured = capsys.readouterr()
    assert "calendar day warnings" in captured.err


def test_main_passes_when_calendar_day_warnings_absent(tmp_path, capsys):
    csv_path = tmp_path / "multi_day.csv"
    _write_multi_day_csv(csv_path)

    rc = check_data_quality.main(
        [
            "--csv",
            str(csv_path),
            "--calendar-day-summary",
            "--calendar-day-coverage-threshold",
            "0.1",
            "--fail-on-calendar-day-warnings",
        ]
    )

    assert rc == 0
    captured = capsys.readouterr()
    assert captured.err == ""


def test_main_posts_webhook_on_failure(monkeypatch, tmp_path, capsys):
    csv_path = tmp_path / "sample.csv"
    _write_sample_csv(csv_path)

    deliveries = []

    def fake_post(url, payload, timeout):
        deliveries.append({"url": url, "payload": payload, "timeout": timeout})
        return True, "status=204"

    monkeypatch.setattr(check_data_quality, "_post_webhook", fake_post)

    out_path = tmp_path / "summary.json"
    rc = check_data_quality.main(
        [
            "--csv",
            str(csv_path),
            "--out-json",
            str(out_path),
            "--fail-under-coverage",
            "0.9",
            "--webhook",
            "https://example.com/hook",
            "--webhook-timeout",
            "7.5",
        ]
    )

    assert rc == 1
    captured = capsys.readouterr()
    assert "FAILURE" in captured.err
    assert deliveries
    record = deliveries[0]
    assert record["url"] == "https://example.com/hook"
    assert record["timeout"] == pytest.approx(7.5)
    payload = record["payload"]
    assert payload["event"] == "data_quality_failure"
    assert payload["failures"]

    saved = json.loads(out_path.read_text(encoding="utf-8"))
    assert saved["webhook"]["targets"] == ["https://example.com/hook"]
    assert saved["webhook"]["deliveries"] == [
        {"url": "https://example.com/hook", "ok": True, "detail": "status=204"}
    ]


def test_main_skips_webhook_without_failures(monkeypatch, tmp_path):
    csv_path = tmp_path / "sample.csv"
    _write_sample_csv(csv_path)

    called = []

    def fake_post(url, payload, timeout):
        called.append((url, payload, timeout))
        return True, "status=200"

    monkeypatch.setattr(check_data_quality, "_post_webhook", fake_post)

    rc = check_data_quality.main(
        [
            "--csv",
            str(csv_path),
            "--fail-under-coverage",
            "0.5",
            "--webhook",
            "https://example.com/hook",
        ]
    )

    assert rc == 0
    assert called == []
