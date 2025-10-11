import csv
import fcntl
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import scripts.analyze_signal_latency as analyze_module
from scripts import _automation_logging


@pytest.fixture(autouse=True)
def _patch_automation_log_paths(tmp_path, monkeypatch):
    log_path = tmp_path / "ops/automation_runs.log"
    seq_path = tmp_path / "ops/automation_runs.sequence"
    monkeypatch.setattr(_automation_logging, "AUTOMATION_LOG_PATH", log_path)
    monkeypatch.setattr(_automation_logging, "AUTOMATION_SEQUENCE_PATH", seq_path)
    
    def _log_with_paths(*args, **kwargs):
        kwargs.setdefault("log_path", log_path)
        kwargs.setdefault("sequence_path", seq_path)
        return _automation_logging.log_automation_event_with_sequence(*args, **kwargs)

    monkeypatch.setattr(analyze_module, "log_automation_event_with_sequence", _log_with_paths)
    return log_path


def _write_raw_csv(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=analyze_module.RAW_FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _row(ts: str, latency_ms: float, status: str = "success"):
    return {
        "timestamp_utc": ts,
        "latency_ms": latency_ms,
        "status": status,
        "detail": "",
        "source": "router",
    }


def test_main_updates_rollups_and_summary(tmp_path, capsys):
    raw_path = tmp_path / "ops/signal_latency.csv"
    rollup_path = tmp_path / "ops/signal_latency_rollup.csv"
    config_path = tmp_path / "configs/latency.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("slo_p95_ms: 2000\nwarning_threshold: 2\n", encoding="utf-8")
    _write_raw_csv(
        raw_path,
        [
            _row("2026-06-29T00:00:00Z", 1200.0),
            _row("2026-06-29T00:05:00Z", 1400.0),
        ],
    )

    args = [
        "--input",
        str(raw_path),
        "--rollup-output",
        str(rollup_path),
        "--alert-config",
        str(config_path),
        "--lock-file",
        str(tmp_path / ".latency.lock"),
        "--archive-dir",
        str(tmp_path / "archive"),
        "--archive-manifest",
        str(tmp_path / "archive/manifest.jsonl"),
        "--heartbeat-file",
        str(tmp_path / "ops/latency_heartbeat.json"),
        "--alerts-dir",
        str(tmp_path / "out/alerts"),
        "--dry-run-alert",
        "--raw-retention-days",
        "30",
        "--rollup-retention-days",
        "60",
        "--job-id",
        "20260629T000000Z-latency",
    ]

    exit_code = analyze_module.main(args)

    assert exit_code == 0
    summary = json.loads(capsys.readouterr().out.strip())
    assert summary["status"] == "dry_run"
    assert summary["samples_analyzed"] == 2
    assert summary["rollups_total"] == 1
    assert summary["job_id"] == "20260629T000000Z-latency"

    rollup_rows = list(csv.DictReader(rollup_path.open(encoding="utf-8")))
    assert len(rollup_rows) == 1
    assert float(rollup_rows[0]["p95_ms"]) >= 1390.0

    heartbeat = json.loads((tmp_path / "ops/latency_heartbeat.json").read_text(encoding="utf-8"))
    assert heartbeat["pending_alerts"] == 0

    log_entries = (tmp_path / "ops/automation_runs.log").read_text(encoding="utf-8").strip().splitlines()
    assert log_entries
    payload = json.loads(log_entries[-1])
    assert payload["status"] == "dry_run"

    dry_run_path = tmp_path / "out/alerts/20260629T000000Z-latency.json"
    if summary["breach_count"]:
        assert dry_run_path.exists()
    else:
        assert not dry_run_path.exists()


def test_breach_streak_and_alerts(tmp_path, capsys):
    raw_path = tmp_path / "ops/signal_latency.csv"
    rollup_path = tmp_path / "ops/signal_latency_rollup.csv"
    heartbeat_path = tmp_path / "ops/latency_heartbeat.json"
    config_path = tmp_path / "configs/latency.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        "slo_p95_ms: 100\nwarning_threshold: 2\ncritical_threshold: 3\nfailure_rate_threshold: 0.5\n",
        encoding="utf-8",
    )
    _write_raw_csv(
        raw_path,
        [
            _row("2026-06-29T00:00:00Z", 150.0),
            _row("2026-06-29T00:10:00Z", 160.0),
        ],
    )

    base_args = [
        "--input",
        str(raw_path),
        "--rollup-output",
        str(rollup_path),
        "--alert-config",
        str(config_path),
        "--lock-file",
        str(tmp_path / ".latency.lock"),
        "--archive-dir",
        str(tmp_path / "archive"),
        "--archive-manifest",
        str(tmp_path / "archive/manifest.jsonl"),
        "--heartbeat-file",
        str(heartbeat_path),
        "--raw-retention-days",
        "30",
        "--rollup-retention-days",
        "60",
        "--job-id",
        "20260629T010000Z-latency",
    ]

    assert analyze_module.main(base_args) == 0
    first_summary = json.loads(capsys.readouterr().out.strip())
    assert first_summary["breach_streak"] == 1
    assert first_summary["status"] == "ok"

    # append another high-latency sample to trigger warning on next run
    with raw_path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=analyze_module.RAW_FIELDNAMES)
        writer.writerow(_row("2026-06-29T00:20:00Z", 170.0))

    assert analyze_module.main(base_args) == 0
    second_summary = json.loads(capsys.readouterr().out.strip())
    assert second_summary["breach_streak"] >= 2
    assert second_summary["status"] == "warning"

    heartbeat = json.loads(heartbeat_path.read_text(encoding="utf-8"))
    assert heartbeat["pending_alerts"] == 1
    assert heartbeat["breach_streak"] == second_summary["breach_streak"]


def test_rotation_generates_manifest(tmp_path, capsys):
    raw_path = tmp_path / "ops/signal_latency.csv"
    rollup_path = tmp_path / "ops/signal_latency_rollup.csv"
    archive_dir = tmp_path / "archive"
    manifest_path = archive_dir / "manifest.jsonl"
    config_path = tmp_path / "configs/latency.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("slo_p95_ms: 5000\n", encoding="utf-8")

    rows = [
        _row("2026-06-29T00:00:00Z", 50.0 + i)
        for i in range(100)
    ]
    _write_raw_csv(raw_path, rows)

    args = [
        "--input",
        str(raw_path),
        "--rollup-output",
        str(rollup_path),
        "--alert-config",
        str(config_path),
        "--lock-file",
        str(tmp_path / ".latency.lock"),
        "--archive-dir",
        str(archive_dir),
        "--archive-manifest",
        str(manifest_path),
        "--heartbeat-file",
        str(tmp_path / "ops/latency_heartbeat.json"),
        "--dry-run-alert",
        "--max-raw-bytes",
        "2048",
        "--job-id",
        "20260629T020000Z-latency",
    ]

    assert analyze_module.main(args) == 0
    summary = json.loads(capsys.readouterr().out.strip())
    assert summary.get("rotated") is not None

    entries = manifest_path.read_text(encoding="utf-8").strip().splitlines()
    assert entries
    manifest_entry = json.loads(entries[-1])
    assert manifest_entry["job_id"] == "20260629T020000Z-latency"
    archive_file = Path(manifest_entry["path"])
    assert archive_file.exists()
    assert archive_file.suffix == ".gz"


def test_lock_skip(tmp_path, capsys):
    raw_path = tmp_path / "ops/signal_latency.csv"
    _write_raw_csv(raw_path, [_row("2026-06-29T00:00:00Z", 10.0)])

    lock_path = tmp_path / ".latency.lock"
    lock_file = lock_path.open("w")
    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    args = [
        "--input",
        str(raw_path),
        "--lock-file",
        str(lock_path),
        "--alert-config",
        str(tmp_path / "configs/config.yaml"),
    ]

    try:
        exit_code = analyze_module.main(args)
    finally:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()

    assert exit_code == 0
    summary = json.loads(capsys.readouterr().out.strip())
    assert summary["status"] == "skipped"
