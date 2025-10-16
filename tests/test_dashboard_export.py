from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from analysis.dashboard import load_ev_history, load_state_slippage, load_turnover_metrics


ARCHIVE_DIR = Path("ops/state_archive/day_orb_5m.DayORB5m/USDJPY/conservative")
RUNS_ROOT = Path("runs")
TELEMETRY_PATH = Path("reports/portfolio_samples/router_demo/telemetry.json")


@pytest.fixture(autouse=True)
def _seed_turnover_samples() -> None:
    index_path = RUNS_ROOT / "index.csv"
    original_contents = index_path.read_text(encoding="utf-8")
    fieldnames = original_contents.splitlines()[0].split(",")
    sample_dir = RUNS_ROOT / "_test_dashboard_turnover"
    sample_dir.mkdir(parents=True, exist_ok=True)
    daily_path = sample_dir / "daily.csv"
    with daily_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["date", "fills"])
        writer.writeheader()
        writer.writerow({"date": "2025-01-01", "fills": "2"})
        writer.writerow({"date": "2025-01-02", "fills": "3"})
    row = {name: "" for name in fieldnames}
    row.update(
        {
            "run_id": "test_dashboard_turnover",
            "run_dir": "runs/_test_dashboard_turnover",
            "timestamp": "20250101_000000",
            "trades": "5",
            "wins": "3",
            "win_rate": "0.6",
        }
    )
    with index_path.open("a", newline="", encoding="utf-8") as handle:
        if original_contents and not original_contents.endswith("\n"):
            handle.write("\n")
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writerow(row)
    yield
    index_path.write_text(original_contents, encoding="utf-8")
    shutil.rmtree(sample_dir)


def test_loaders_return_data():
    ev_history = load_ev_history(ARCHIVE_DIR, limit=5)
    assert ev_history, "EV snapshots should not be empty"
    assert ev_history[-1].win_rate_lcb is not None

    slip = load_state_slippage(ARCHIVE_DIR, limit=3)
    assert slip, "State slippage snapshots should not be empty"
    assert any(s.coefficients for s in slip)

    turnover = load_turnover_metrics(RUNS_ROOT, limit=3)
    assert turnover, "Turnover snapshots should not be empty"


def test_export_dashboard_cli(tmp_path):
    latency_rollup = tmp_path / "latency.csv"
    _write_latency_rollup(latency_rollup)
    output_dir = tmp_path / "dashboard"
    manifest_path = output_dir / "manifest.json"
    heartbeat_path = tmp_path / "heartbeat.json"
    history_dir = tmp_path / "history"
    archive_manifest = tmp_path / "archive_manifest.jsonl"
    summary_path = tmp_path / "summary.json"
    cmd = [
        sys.executable,
        "analysis/export_dashboard_data.py",
        "--runs-root",
        str(RUNS_ROOT),
        "--state-archive-root",
        str(Path("ops/state_archive")),
        "--strategy",
        "day_orb_5m.DayORB5m",
        "--symbol",
        "USDJPY",
        "--mode",
        "conservative",
        "--portfolio-telemetry",
        str(TELEMETRY_PATH),
        "--latency-rollup",
        str(latency_rollup),
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
        "--history-retention-days",
        "9999",
        "--json-out",
        str(summary_path),
        "--job-id",
        "20240101T000000Z-dashboard",
        "--indent",
        "0",
    ]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    assert result.stdout.strip(), "CLI should emit summary"

    datasets = {
        "ev_history": output_dir / "ev_history.json",
        "slippage": output_dir / "slippage.json",
        "turnover": output_dir / "turnover.json",
        "latency": output_dir / "latency.json",
    }
    for path in datasets.values():
        assert path.exists(), f"dataset missing: {path.name}"

    manifest = json.loads(manifest_path.read_text())
    assert manifest["sequence"] == 1
    assert {item["dataset"] for item in manifest["datasets"]} == set(datasets)

    summary = json.loads(summary_path.read_text())
    assert summary["status"] == "ok"
    assert summary["datasets"] == {name: "ok" for name in datasets}
    heartbeat = json.loads(heartbeat_path.read_text())
    assert heartbeat["datasets"]["ev_history"] == "ok"
    assert (history_dir / "20240101T000000Z-dashboard" / "ev_history.json").exists()


def _write_latency_rollup(path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "hour_utc",
                "window_end_utc",
                "count",
                "failure_count",
                "failure_rate",
                "p50_ms",
                "p95_ms",
                "p99_ms",
                "max_ms",
                "breach_flag",
                "breach_streak",
            ]
        )
        writer.writerow(
            [
                "2024-01-01T00:00:00Z",
                "2024-01-01T01:00:00Z",
                "10",
                "1",
                "0.1",
                "120",
                "180",
                "220",
                "300",
                "true",
                "2",
            ]
        )
