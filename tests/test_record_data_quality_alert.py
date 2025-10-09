from pathlib import Path

import subprocess
import sys

import pytest

from scripts import record_data_quality_alert


def run_cli(tmp_path: Path, args: list[str]) -> subprocess.CompletedProcess:
    cmd = [
        sys.executable,
        str(Path(record_data_quality_alert.__file__).resolve()),
        *args,
    ]
    return subprocess.run(cmd, check=True, capture_output=True, text=True, cwd=tmp_path)


def test_creates_log_when_missing(tmp_path: Path):
    log_path = tmp_path / "ops/health/data_quality_alerts.md"
    args = [
        "--alert-timestamp",
        "2025-10-10T12:00:00Z",
        "--symbol",
        "USDJPY",
        "--coverage-ratio",
        "0.987",
        "--ack-by",
        "codex",
        "--status",
        "investigating",
        "--remediation",
        "Re-run audit",
        "--log-path",
        str(log_path),
    ]

    run_cli(tmp_path, args)

    contents = log_path.read_text(encoding="utf-8")
    assert "alert_timestamp (UTC)" in contents
    assert "| 2025-10-10T12:00:00Z | USDJPY | 5m | 0.9870" in contents


def test_inserts_row_above_existing_entries(tmp_path: Path):
    log_path = tmp_path / "ops/health/data_quality_alerts.md"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        "| alert_timestamp (UTC) | symbol | tf | coverage_ratio | ack_by | ack_timestamp (UTC) | status | remediation | follow_up |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
        "| 2025-10-09T12:13:30Z | USDJPY | 5m | 0.1423 | codex | 2025-10-09T12:13:30Z | resolved | Dry run | note |\n",
        encoding="utf-8",
    )

    args = [
        "--alert-timestamp",
        "2025-11-01T08:00:00Z",
        "--symbol",
        "EURUSD",
        "--coverage-ratio",
        "0.995",
        "--ack-by",
        "ops",
        "--status",
        "resolved",
        "--log-path",
        str(log_path),
        "--ack-timestamp",
        "2025-11-01T08:05:00Z",
    ]

    run_cli(tmp_path, args)

    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert lines[2].startswith("| 2025-11-01T08:00:00Z | EURUSD")
    assert lines[3].startswith("| 2025-10-09T12:13:30Z | USDJPY")
