import json
import statistics
import subprocess
import sys
from pathlib import Path

import pytest


DAY_MANIFEST = Path("configs/strategies/day_orb_5m.yaml")
SCALPING_MANIFEST = Path("configs/strategies/tokyo_micro_mean_reversion.yaml")


def _write_metrics(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")


def _compute_expected_correlation(values_a, values_b) -> float:
    returns_a = [values_a[i] - values_a[i - 1] for i in range(1, len(values_a))]
    returns_b = [values_b[i] - values_b[i - 1] for i in range(1, len(values_b))]
    return statistics.correlation(returns_a, returns_b)


def test_build_router_snapshot_cli_generates_portfolio_summary(tmp_path: Path) -> None:
    day_run = tmp_path / "runs" / "day"
    scalping_run = tmp_path / "runs" / "scalping"

    day_curve = [
        ["2025-01-01T00:00:00Z", 100000.0],
        ["2025-01-02T00:00:00Z", 100400.0],
        ["2025-01-03T00:00:00Z", 100150.0],
        ["2025-01-04T00:00:00Z", 100900.0],
    ]
    scalping_curve = [
        ["2025-01-01T00:00:00Z", 60000.0],
        ["2025-01-02T00:00:00Z", 60200.0],
        ["2025-01-03T00:00:00Z", 60100.0],
        ["2025-01-04T00:00:00Z", 60500.0],
    ]

    _write_metrics(
        day_run / "metrics.json",
        {
            "trades": 3,
            "equity_curve": day_curve,
            "runtime": {"execution_health": {"reject_rate": 0.01, "slippage_bps": 3.0}},
        },
    )
    _write_metrics(
        scalping_run / "metrics.json",
        {
            "trades": 3,
            "equity_curve": scalping_curve,
            "runtime": {"execution_health": {"reject_rate": 0.03, "slippage_bps": 6.0}},
        },
    )

    snapshot_dir = tmp_path / "snapshot"
    cmd = [
        sys.executable,
        "scripts/build_router_snapshot.py",
        "--output",
        str(snapshot_dir),
        "--manifest",
        str(DAY_MANIFEST),
        "--manifest",
        str(SCALPING_MANIFEST),
        "--manifest-run",
        f"day_orb_5m_v1={day_run}",
        "--manifest-run",
        f"tokyo_micro_mean_reversion_v0={scalping_run}",
        "--positions",
        "day_orb_5m_v1=1",
        "--positions",
        "tokyo_micro_mean_reversion_v0=2",
        "--correlation-window-minutes",
        "240",
        "--indent",
        "2",
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)

    telemetry_path = snapshot_dir / "telemetry.json"
    assert telemetry_path.exists()
    telemetry = json.loads(telemetry_path.read_text(encoding="utf-8"))

    assert telemetry["active_positions"] == {"day_orb_5m_v1": 1, "tokyo_micro_mean_reversion_v0": 2}
    assert telemetry["execution_health"]["day_orb_5m_v1"]["reject_rate"] == pytest.approx(0.01)
    assert telemetry["execution_health"]["tokyo_micro_mean_reversion_v0"]["slippage_bps"] == pytest.approx(6.0)
    assert telemetry["gross_exposure_pct"] == pytest.approx(0.33, rel=1e-6)
    assert telemetry["correlation_window_minutes"] == pytest.approx(240.0)

    corr_value = telemetry["strategy_correlations"]["day_orb_5m_v1"]["tokyo_micro_mean_reversion_v0"]
    expected_corr = _compute_expected_correlation(
        [point[1] for point in day_curve],
        [point[1] for point in scalping_curve],
    )
    assert corr_value == pytest.approx(expected_corr, rel=1e-6)

    metrics_dir = snapshot_dir / "metrics"
    day_metrics_path = metrics_dir / "day_orb_5m_v1.json"
    scalping_metrics_path = metrics_dir / "tokyo_micro_mean_reversion_v0.json"
    assert day_metrics_path.exists()
    assert scalping_metrics_path.exists()

    day_payload = json.loads(day_metrics_path.read_text(encoding="utf-8"))
    assert day_payload["manifest_path"] == "configs/strategies/day_orb_5m.yaml"
    assert day_payload["equity_curve"] == day_curve

    copied_manifest = metrics_dir / "configs" / "strategies" / "day_orb_5m.yaml"
    assert copied_manifest.exists()

    summary_path = tmp_path / "summary.json"
    subprocess.run(
        [
            sys.executable,
            "scripts/report_portfolio_summary.py",
            "--input",
            str(snapshot_dir),
            "--output",
            str(summary_path),
            "--indent",
            "2",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["input_dir"].endswith(str(snapshot_dir))
    gross = summary["gross_exposure"]
    assert gross["current_pct"] == pytest.approx(0.33, rel=1e-6)

    heatmap = {
        (row["source"], row["target"]): row["correlation"]
        for row in summary["correlation_heatmap"]
    }
    assert heatmap[("day_orb_5m_v1", "tokyo_micro_mean_reversion_v0")] == pytest.approx(expected_corr, rel=1e-6)
    assert summary["correlation_window_minutes"] == pytest.approx(240.0)


def test_build_router_snapshot_help_lists_correlation_window_flag() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/build_router_snapshot.py", "--help"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "--correlation-window-minutes" in result.stdout
