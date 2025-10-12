import json
import subprocess
import sys
from pathlib import Path


RUNS_ROOT = Path("runs")
ARCHIVE_ROOT = Path("ops/state_archive")
TELEMETRY_PATH = Path("reports/portfolio_samples/router_demo/telemetry.json")


def test_manifest_sequence_increments_and_history(tmp_path):
    latency_path = tmp_path / "latency.csv"
    _write_latency_rollup(latency_path)
    output_dir = tmp_path / "dashboard"
    manifest_path = output_dir / "manifest.json"
    heartbeat_path = tmp_path / "heartbeat.json"
    history_dir = tmp_path / "history"
    archive_manifest = tmp_path / "archive_manifest.jsonl"

    summary_first = _run_cli(
        job_id="20240101T000000Z-dashboard",
        output_dir=output_dir,
        manifest_path=manifest_path,
        heartbeat_path=heartbeat_path,
        history_dir=history_dir,
        archive_manifest=archive_manifest,
        latency_path=latency_path,
        history_retention_days=9999,
    )

    expected_archive_dir = str((ARCHIVE_ROOT / "day_orb_5m.DayORB5m" / "USDJPY" / "conservative").resolve())
    expected_runs_root = str(RUNS_ROOT.resolve())
    expected_latency = str(latency_path.resolve())
    expected_telemetry = str(TELEMETRY_PATH.resolve())

    ev_payload = json.loads((output_dir / "ev_history.json").read_text())
    assert ev_payload["dataset"] == "ev_history"
    assert ev_payload["job_id"] == summary_first["job_id"]
    assert ev_payload["sources"] == {"archive_dir": expected_archive_dir}

    slippage_payload = json.loads((output_dir / "slippage.json").read_text())
    assert slippage_payload["sources"] == {
        "archive_dir": expected_archive_dir,
        "portfolio_telemetry": expected_telemetry,
    }

    turnover_payload = json.loads((output_dir / "turnover.json").read_text())
    assert turnover_payload["sources"] == {"runs_root": expected_runs_root}

    latency_payload = json.loads((output_dir / "latency.json").read_text())
    assert latency_payload["sources"] == {"latency_rollup": expected_latency}
    assert len(latency_payload["rows"]) == 1

    summary_second = _run_cli(
        job_id="20240102T000000Z-dashboard",
        output_dir=output_dir,
        manifest_path=manifest_path,
        heartbeat_path=heartbeat_path,
        history_dir=history_dir,
        archive_manifest=archive_manifest,
        latency_path=latency_path,
        history_retention_days=9999,
    )

    manifest = json.loads(manifest_path.read_text())
    assert manifest["sequence"] == 2
    assert len(manifest["datasets"]) == 4

    heartbeat = json.loads(heartbeat_path.read_text())
    assert heartbeat["datasets"]["latency"] == "ok"
    assert heartbeat["last_success_at"].endswith("Z")

    history_dirs = sorted(p.name for p in history_dir.iterdir() if p.is_dir())
    assert history_dirs == ["20240101T000000Z-dashboard", "20240102T000000Z-dashboard"]

    assert not archive_manifest.exists() or not archive_manifest.read_text().strip()
    assert summary_second["status"] == "ok"


def test_upload_command_failure_sets_error(tmp_path):
    latency_path = tmp_path / "latency.csv"
    _write_latency_rollup(latency_path)
    output_dir = tmp_path / "dashboard"
    manifest_path = output_dir / "manifest.json"
    heartbeat_path = tmp_path / "heartbeat.json"
    history_dir = tmp_path / "history"
    archive_manifest = tmp_path / "archive_manifest.jsonl"
    summary_path = tmp_path / "summary.json"

    fail_command = f"{sys.executable} -c \"import sys; sys.exit(3)\""
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
            "20240103T000000Z-dashboard",
            "--history-retention-days",
            "9999",
            "--upload-command",
            fail_command,
            "--indent",
            "0",
        ],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 1

    summary = json.loads(summary_path.read_text())
    assert summary["status"] == "error"
    assert summary["datasets"]["latency"] == "ok"
    assert summary.get("upload", {}).get("returncode") == 3

    heartbeat = json.loads(heartbeat_path.read_text())
    assert heartbeat["last_failure"]["errors"]


def _run_cli(
    *,
    job_id: str,
    output_dir: Path,
    manifest_path: Path,
    heartbeat_path: Path,
    history_dir: Path,
    archive_manifest: Path,
    latency_path: Path,
    history_retention_days: int,
) -> dict:
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
            str(history_retention_days),
            "--indent",
            "0",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    return json.loads(summary_path.read_text())


def _write_latency_rollup(path: Path) -> None:
    with path.open("w", encoding="utf-8") as handle:
        handle.write(
            "hour_utc,window_end_utc,count,failure_count,failure_rate,p50_ms,p95_ms,p99_ms,max_ms\n"
        )
        handle.write(
            "2024-01-01T00:00:00Z,2024-01-01T01:00:00Z,10,1,0.1,120,180,220,300\n"
        )
