from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import scripts.verify_observability_job as verify_module
from scripts import _automation_logging


@pytest.fixture(autouse=True)
def _patch_automation_logging_paths(tmp_path, monkeypatch):
    log_path = tmp_path / "ops/automation_runs.log"
    sequence_path = tmp_path / "ops/automation_runs.sequence"

    monkeypatch.setattr(verify_module, "AUTOMATION_LOG_PATH", log_path)
    monkeypatch.setattr(verify_module, "AUTOMATION_SEQUENCE_PATH", sequence_path)
    monkeypatch.setattr(_automation_logging, "AUTOMATION_LOG_PATH", log_path)
    monkeypatch.setattr(_automation_logging, "AUTOMATION_SEQUENCE_PATH", sequence_path)

    def _log_with_paths(job_id: str, status: str, **kwargs):
        kwargs.setdefault("log_path", log_path)
        kwargs.setdefault("sequence_path", sequence_path)
        kwargs.setdefault("schema_path", verify_module.AUTOMATION_SCHEMA_PATH)
        return _automation_logging.log_automation_event_with_sequence(job_id, status, **kwargs)

    monkeypatch.setattr(verify_module, "log_automation_event_with_sequence", _log_with_paths)
    return log_path, sequence_path


def _seed_log_entry(job_name: str, status: str, *, log_path: Path, sequence_path: Path) -> None:
    job_id = _automation_logging.generate_job_id(job_name)
    _automation_logging.log_automation_event_with_sequence(
        job_id,
        status,
        log_path=log_path,
        sequence_path=sequence_path,
        schema_path=verify_module.AUTOMATION_SCHEMA_PATH,
    )


def _write_heartbeat(path: Path, *, hours_ago: float) -> None:
    timestamp = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    payload = {"last_success_at": timestamp.isoformat().replace("+00:00", "Z"), "pending_alerts": 0}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_manifest(path: Path) -> None:
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    payload = {
        "sequence": 2,
        "generated_at": now_iso,
        "job_id": "20260701T000000Z-dashboard",
        "datasets": [
            {
                "dataset": "ev_history",
                "path": "out/dashboard/ev_history.json",
                "checksum_sha256": "a" * 64,
                "row_count": 10,
                "generated_at": now_iso,
                "source_hash": "b" * 64,
            },
            {
                "dataset": "latency",
                "path": "out/dashboard/latency.json",
                "checksum_sha256": "c" * 64,
                "row_count": 24,
                "generated_at": now_iso,
                "source_hash": "d" * 64,
            },
        ],
        "provenance": {
            "command": "python3 analysis/export_dashboard_data.py",
            "commit_sha": "abcdef1234567890",
            "inputs": ["runs/index.csv"],
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_verify_observability_job_success(tmp_path, capsys, monkeypatch, _patch_automation_logging_paths):
    log_path, sequence_path = _patch_automation_logging_paths
    _seed_log_entry("latency", "ok", log_path=log_path, sequence_path=sequence_path)
    _seed_log_entry("weekly", "ok", log_path=log_path, sequence_path=sequence_path)

    heartbeat_path = tmp_path / "ops/latency_job_heartbeat.json"
    _write_heartbeat(heartbeat_path, hours_ago=1.0)

    manifest_path = tmp_path / "out/dashboard/manifest.json"
    _write_manifest(manifest_path)

    monkeypatch.setenv("OBS_WEEKLY_WEBHOOK_URL", "https://example.invalid/webhook")
    monkeypatch.setenv("OBS_WEBHOOK_SECRET", "secret-token")

    args = [
        "--job-id",
        "20260701T120000Z-verification",
        "--check-log",
        str(log_path),
        "--sequence-file",
        str(sequence_path),
        "--heartbeat",
        str(heartbeat_path),
        "--heartbeat-max-age-hours",
        "6",
        "--dashboard-manifest",
        str(manifest_path),
        "--expected-dataset",
        "ev_history",
        "--expected-dataset",
        "latency",
        "--check-secrets",
        "--secret",
        "OBS_WEEKLY_WEBHOOK_URL",
        "--secret",
        "OBS_WEBHOOK_SECRET",
    ]

    exit_code = verify_module.main(args)
    assert exit_code == 0

    summary = json.loads(capsys.readouterr().out.strip())
    assert summary["status"] == "ok"
    assert summary["job_id"] == "20260701T120000Z-verification"
    assert any(check["name"] == "automation_log" and check["status"] == "ok" for check in summary["checks"])

    log_lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(log_lines) == 3  # two seeded entries + verification job
    final_entry = json.loads(log_lines[-1])
    assert final_entry["job_id"] == "20260701T120000Z-verification"
    assert final_entry["status"] == "ok"
    diagnostics = final_entry["diagnostics"]
    assert diagnostics["checks"]


def test_verify_observability_job_detects_stale_heartbeat(
    tmp_path, capsys, monkeypatch, _patch_automation_logging_paths
):
    log_path, sequence_path = _patch_automation_logging_paths
    _seed_log_entry("latency", "ok", log_path=log_path, sequence_path=sequence_path)

    stale_heartbeat = tmp_path / "ops/weekly_report_heartbeat.json"
    _write_heartbeat(stale_heartbeat, hours_ago=12.0)

    manifest_path = tmp_path / "out/dashboard/manifest.json"
    _write_manifest(manifest_path)

    monkeypatch.setenv("OBS_WEEKLY_WEBHOOK_URL", "https://example.invalid/webhook")
    monkeypatch.setenv("OBS_WEBHOOK_SECRET", "secret-token")

    args = [
        "--job-id",
        "20260701T130000Z-verification",
        "--check-log",
        str(log_path),
        "--sequence-file",
        str(sequence_path),
        "--heartbeat",
        str(stale_heartbeat),
        "--heartbeat-max-age-hours",
        "6",
        "--dashboard-manifest",
        str(manifest_path),
        "--check-secrets",
        "--secret",
        "OBS_WEEKLY_WEBHOOK_URL",
        "--secret",
        "OBS_WEBHOOK_SECRET",
    ]

    exit_code = verify_module.main(args)
    assert exit_code == 1

    summary = json.loads(capsys.readouterr().out.strip())
    assert summary["status"] == "error"
    assert summary["failures"]
    assert any(failure["code"] == "heartbeat_stale" for failure in summary["failures"])

    log_lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    final_entry = json.loads(log_lines[-1])
    assert final_entry["job_id"] == "20260701T130000Z-verification"
    assert final_entry["status"] == "error"
    assert final_entry["diagnostics"]["error_code"] == "verification_failed"

