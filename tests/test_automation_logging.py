from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts._automation_context import AutomationContext, build_automation_context
from scripts._automation_logging import (
    AUTOMATION_SCHEMA_PATH,
    AutomationLogError,
    AutomationLogSchemaError,
    generate_job_id,
    log_automation_event,
    log_automation_event_with_sequence,
)


def test_generate_job_id_format():
    when = datetime(2026, 6, 28, 12, 30, 15, tzinfo=timezone.utc)
    job_id = generate_job_id("Latency Monitor", when=when)
    assert job_id == "20260628T123015Z-latency-monitor"


def test_log_automation_event_writes_entry(tmp_path):
    log_path = tmp_path / "automation.log"
    schema_path = Path(AUTOMATION_SCHEMA_PATH)
    job_id = generate_job_id("weekly-report")
    entry = log_automation_event(
        job_id,
        "ok",
        log_path=log_path,
        schema_path=schema_path,
        duration_ms=1200,
        attempts=1,
        artefacts=["ops/weekly_report_history/2026-06-28.json"],
        diagnostics={"config_version": "2026-06-28"},
    )

    assert entry["job_id"] == job_id
    assert entry["status"] == "ok"
    assert entry["duration_ms"] == 1200
    log_content = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(log_content) == 1
    parsed = json.loads(log_content[0])
    assert parsed["job_id"] == job_id
    assert parsed["artefacts"] == ["ops/weekly_report_history/2026-06-28.json"]


def test_log_automation_event_sequence_increment(tmp_path):
    log_path = tmp_path / "automation.log"
    sequence_path = tmp_path / "automation.sequence"
    schema_path = Path(AUTOMATION_SCHEMA_PATH)

    first = log_automation_event_with_sequence(
        generate_job_id("latency"),
        "ok",
        log_path=log_path,
        sequence_path=sequence_path,
        schema_path=schema_path,
    )
    second = log_automation_event_with_sequence(
        generate_job_id("latency"),
        "error",
        log_path=log_path,
        sequence_path=sequence_path,
        schema_path=schema_path,
    )

    assert first["sequence"] == 1
    assert second["sequence"] == 2
    sequence_data = json.loads(sequence_path.read_text(encoding="utf-8"))
    assert sequence_data["value"] == 2


def test_log_automation_event_sequence_gap_warning(tmp_path):
    log_path = tmp_path / "automation.log"
    sequence_path = tmp_path / "automation.sequence"
    schema_path = Path(AUTOMATION_SCHEMA_PATH)

    # Seed three entries and then remove the latest log line to simulate a missing sequence.
    first = log_automation_event_with_sequence(
        generate_job_id("latency"),
        "ok",
        log_path=log_path,
        sequence_path=sequence_path,
        schema_path=schema_path,
    )
    second = log_automation_event_with_sequence(
        generate_job_id("latency"),
        "ok",
        log_path=log_path,
        sequence_path=sequence_path,
        schema_path=schema_path,
    )
    third = log_automation_event_with_sequence(
        generate_job_id("latency"),
        "ok",
        log_path=log_path,
        sequence_path=sequence_path,
        schema_path=schema_path,
    )
    assert first["sequence"] == 1
    assert second["sequence"] == 2
    assert third["sequence"] == 3

    log_lines = log_path.read_text(encoding="utf-8").splitlines()
    log_path.write_text(
        "\n".join(log_lines[:-1]) + ("\n" if log_lines[:-1] else ""),
        encoding="utf-8",
    )

    # Confirm the sequence file still records the removed value.
    sequence_contents = json.loads(sequence_path.read_text(encoding="utf-8"))
    assert sequence_contents["value"] == 3

    job_id = generate_job_id("latency")
    entry = log_automation_event_with_sequence(
        job_id,
        "ok",
        log_path=log_path,
        sequence_path=sequence_path,
        schema_path=schema_path,
    )
    assert entry["sequence"] == 4

    parsed_entries = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert parsed_entries[-1]["sequence"] == 4
    warning_entry = parsed_entries[-2]
    assert warning_entry["status"] == "warning"
    diagnostics = warning_entry["diagnostics"]
    assert diagnostics["error_code"] == "sequence_gap"
    assert diagnostics["expected_previous_sequence"] == 3
    assert diagnostics["observed_previous_sequence"] == 2
    assert diagnostics["next_sequence"] == 4
    assert diagnostics["gap_size"] == 1
    assert diagnostics["gap_direction"] == "observed_lower"
    assert diagnostics["detected_for_job_id"] == job_id

    updated_sequence_contents = json.loads(sequence_path.read_text(encoding="utf-8"))
    assert updated_sequence_contents["value"] == 4


def test_log_automation_event_rejects_invalid_status(tmp_path):
    log_path = tmp_path / "automation.log"
    schema_path = Path(AUTOMATION_SCHEMA_PATH)
    with pytest.raises(AutomationLogSchemaError):
        log_automation_event("20260628T000000Z-demo", "invalid", log_path=log_path, schema_path=schema_path)


def test_log_automation_event_size_guard(tmp_path):
    log_path = tmp_path / "automation.log"
    schema_path = Path(AUTOMATION_SCHEMA_PATH)
    with pytest.raises(AutomationLogError):
        log_automation_event(
            generate_job_id("dashboard-export"),
            "ok",
            log_path=log_path,
            schema_path=schema_path,
            diagnostics={"details": "x" * 5000},
        )


def test_build_automation_context_redacts_env():
    env = {
        "OBS_SECRET": "super-secret",
        "CI_COMMIT_SHA": "commit123",
        "RUN_ID": "9876",
    }
    argv = ["python", "scripts/run_daily_workflow.py", "--observability"]
    when = datetime(2026, 6, 29, 9, 0, tzinfo=timezone.utc)
    context = build_automation_context(
        "observability", env=env, argv=argv, metadata={"config": "default"}, when=when
    )

    assert isinstance(context, AutomationContext)
    assert context.commit_sha == "commit123"
    assert context.get_secret("OBS_SECRET") == "super-secret"
    assert context.job_id.startswith("20260629T090000Z-observability")

    described = context.describe()
    assert described["environment"]["OBS_SECRET"] == "<redacted>"
    assert described["environment"]["RUN_ID"] == "9876"
    payload = context.as_log_payload(include_environment=True)
    assert "environment" in payload
    assert payload["environment"]["OBS_SECRET"] == "<redacted>"
