from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


RUNS_ROOT = Path("runs")
ARCHIVE_ROOT = Path("ops/state_archive")
TELEMETRY_PATH = Path("reports/portfolio_samples/router_demo/telemetry.json")


def test_verify_dashboard_bundle_success(tmp_path):
    latency_path = tmp_path / "latency.csv"
    _write_latency_rollup(latency_path)
    output_dir = tmp_path / "dashboard"
    manifest_path = output_dir / "manifest.json"
    heartbeat_path = tmp_path / "heartbeat.json"
    history_dir = tmp_path / "history"
    archive_manifest = tmp_path / "archive_manifest.jsonl"

    _run_export(
        job_id="20240101T000000Z-dashboard",
        output_dir=output_dir,
        manifest_path=manifest_path,
        heartbeat_path=heartbeat_path,
        history_dir=history_dir,
        archive_manifest=archive_manifest,
        latency_path=latency_path,
    )

    summary_path = tmp_path / "verify_summary.json"
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/verify_dashboard_bundle.py",
            "--manifest",
            str(manifest_path),
            "--history-dir",
            str(history_dir),
            "--archive-manifest",
            str(archive_manifest),
            "--retention-days",
            "9999",
            "--expected-dataset",
            "ev_history",
            "--expected-dataset",
            "slippage",
            "--expected-dataset",
            "turnover",
            "--expected-dataset",
            "latency",
            "--json-out",
            str(summary_path),
            "--job-id",
            "20240101T010101Z-verify",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0

    summary = json.loads(summary_path.read_text())
    assert summary["status"] == "ok"
    datasets = summary["datasets"]
    for name in ("ev_history", "slippage", "turnover", "latency"):
        assert datasets[name]["status"] == "ok"
        assert "checksum_sha256" in datasets[name]


def test_verify_dashboard_bundle_detects_checksum_mismatch(tmp_path):
    latency_path = tmp_path / "latency.csv"
    _write_latency_rollup(latency_path)
    output_dir = tmp_path / "dashboard"
    manifest_path = output_dir / "manifest.json"
    heartbeat_path = tmp_path / "heartbeat.json"
    history_dir = tmp_path / "history"
    archive_manifest = tmp_path / "archive_manifest.jsonl"

    _run_export(
        job_id="20240102T000000Z-dashboard",
        output_dir=output_dir,
        manifest_path=manifest_path,
        heartbeat_path=heartbeat_path,
        history_dir=history_dir,
        archive_manifest=archive_manifest,
        latency_path=latency_path,
    )

    ev_history_path = output_dir / "ev_history.json"
    payload = json.loads(ev_history_path.read_text())
    if isinstance(payload, dict) and payload.get("rows"):
        first_row = payload["rows"][0]
        if isinstance(first_row, dict) and "alpha" in first_row:
            first_row["alpha"] = float(first_row["alpha"]) + 1.0
    ev_history_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    summary_path = tmp_path / "verify_summary_error.json"
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/verify_dashboard_bundle.py",
            "--manifest",
            str(manifest_path),
            "--history-dir",
            str(history_dir),
            "--archive-manifest",
            str(archive_manifest),
            "--retention-days",
            "9999",
            "--expected-dataset",
            "ev_history",
            "--expected-dataset",
            "slippage",
            "--expected-dataset",
            "turnover",
            "--expected-dataset",
            "latency",
            "--json-out",
            str(summary_path),
            "--job-id",
            "20240102T010101Z-verify",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 1

    summary = json.loads(summary_path.read_text())
    assert summary["status"] == "error"
    ev_status = summary["datasets"]["ev_history"]
    assert ev_status["status"] == "error"
    assert any("Checksum mismatch" in message for message in ev_status.get("messages", []))


def _run_export(
    *,
    job_id: str,
    output_dir: Path,
    manifest_path: Path,
    heartbeat_path: Path,
    history_dir: Path,
    archive_manifest: Path,
    latency_path: Path,
) -> None:
    summary_path = output_dir.parent / f"summary_{job_id}.json"
    completed = subprocess.run(
        [
            sys.executable,
            "analysis/export_dashboard_data.py",
            "--runs-root",
            str(RUNS_ROOT),
            "--state-archive-root",
            str(ARCHIVE_ROOT),
            "--strategy",
            "day_orb_5m.DayORB5m",
            "--symbol",
            "USDJPY",
            "--mode",
            "conservative",
            "--portfolio-telemetry",
            str(TELEMETRY_PATH),
            "--latency-rollup",
            str(latency_path),
            "--dataset",
            "ev_history",
            "--dataset",
            "slippage",
            "--dataset",
            "turnover",
            "--dataset",
            "latency",
            "--output-dir",
            str(output_dir),
            "--manifest",
            str(manifest_path),
            "--heartbeat-file",
            str(heartbeat_path),
            "--history-dir",
            str(history_dir),
            "--archive-manifest",
            str(archive_manifest),
            "--json-out",
            str(summary_path),
            "--job-id",
            job_id,
            "--history-retention-days",
            "9999",
            "--indent",
            "0",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0


def _write_latency_rollup(path: Path) -> None:
    with path.open("w", encoding="utf-8") as handle:
        handle.write(
            "hour_utc,window_end_utc,count,failure_count,failure_rate,p50_ms,p95_ms,p99_ms,max_ms\n"
        )
        handle.write(
            "2024-01-01T00:00:00Z,2024-01-01T01:00:00Z,10,1,0.1,120,180,220,300\n"
        )
