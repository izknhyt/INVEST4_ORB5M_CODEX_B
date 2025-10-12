import json
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Dict, Tuple

import pytest

from scripts import build_router_snapshot as build_router_snapshot_module


DAY_MANIFEST = Path("configs/strategies/day_orb_5m.yaml")
SCALPING_MANIFEST = Path("configs/strategies/tokyo_micro_mean_reversion.yaml")
ROUTER_SAMPLE_METRICS = Path("reports/portfolio_samples/router_demo/metrics")


def _load_router_demo_metrics(manifest_id: str) -> Tuple[Path, Dict[str, object]]:
    metrics_path = (ROUTER_SAMPLE_METRICS / f"{manifest_id}.json").resolve()
    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    return metrics_path, payload


def _write_metrics(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")


def _compute_expected_correlation(values_a, values_b) -> float:
    returns_a = [values_a[i] - values_a[i - 1] for i in range(1, len(values_a))]
    returns_b = [values_b[i] - values_b[i - 1] for i in range(1, len(values_b))]
    return statistics.correlation(returns_a, returns_b)


def _build_router_snapshot_from_samples(tmp_path: Path) -> Path:
    snapshot_dir = tmp_path / "router_demo_snapshot"
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
        f"day_orb_5m_v1={ROUTER_SAMPLE_METRICS / 'day_orb_5m_v1.json'}",
        "--manifest-run",
        f"tokyo_micro_mean_reversion_v0={ROUTER_SAMPLE_METRICS / 'tokyo_micro_mean_reversion_v0.json'}",
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
    return snapshot_dir


def _mutate_budget_headroom(snapshot_dir: Path) -> None:
    telemetry_path = snapshot_dir / "telemetry.json"
    payload = json.loads(telemetry_path.read_text(encoding="utf-8"))
    payload["category_utilisation_pct"]["day"] = 0.0
    payload["category_utilisation_pct"]["scalping"] = 0.0
    payload["active_positions"]["day_orb_5m_v1"] = 144
    payload["active_positions"]["tokyo_micro_mean_reversion_v0"] = 400
    payload["category_budget_headroom_pct"]["day"] = 4.0
    payload["category_budget_headroom_pct"]["scalping"] = -1.0
    telemetry_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


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
    meta_entry = telemetry["correlation_meta"]["day_orb_5m_v1"]["tokyo_micro_mean_reversion_v0"]
    assert meta_entry["strategy_id"] == "tokyo_micro_mean_reversion_v0"
    assert meta_entry["bucket_category"] == "scalping"
    assert meta_entry["bucket_budget_pct"] == pytest.approx(15.0)

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

    categories = {row["category"]: row for row in summary["category_utilisation"]}
    assert set(categories) == {"day", "scalping"}

    day_entry = categories["day"]
    assert day_entry["budget_pct"] == pytest.approx(40.0)
    assert day_entry["budget_status"] == "ok"
    assert day_entry["budget_headroom_pct"] == pytest.approx(
        day_entry["budget_pct"] - day_entry["utilisation_pct"],
        rel=1e-6,
        abs=1e-9,
    )
    assert day_entry["budget_utilisation_ratio"] == pytest.approx(
        day_entry["utilisation_pct"] / day_entry["budget_pct"], rel=1e-6
    )
    assert "budget_over_pct" not in day_entry

    scalping_entry = categories["scalping"]
    assert scalping_entry["budget_pct"] == pytest.approx(15.0)
    assert scalping_entry["budget_status"] == "ok"
    assert scalping_entry["budget_headroom_pct"] == pytest.approx(
        scalping_entry["budget_pct"] - scalping_entry["utilisation_pct"],
        rel=1e-6,
        abs=1e-9,
    )
    assert scalping_entry["budget_utilisation_ratio"] == pytest.approx(
        scalping_entry["utilisation_pct"] / scalping_entry["budget_pct"],
        rel=1e-6,
    )
    assert "budget_over_pct" not in scalping_entry

    heatmap = {
        (row["source"], row["target"]): row
        for row in summary["correlation_heatmap"]
    }
    primary_entry = heatmap[("day_orb_5m_v1", "tokyo_micro_mean_reversion_v0")]
    assert primary_entry["correlation"] == pytest.approx(expected_corr, rel=1e-6)
    assert primary_entry["target_strategy_id"] == "tokyo_micro_mean_reversion_v0"
    assert primary_entry["bucket_category"] == "scalping"
    assert primary_entry["bucket_budget_pct"] == pytest.approx(15.0)
    assert summary["correlation_window_minutes"] == pytest.approx(240.0)


def test_build_router_snapshot_cli_accepts_zero_equity(tmp_path: Path) -> None:
    day_run = tmp_path / "runs" / "day_zero"
    scalping_run = tmp_path / "runs" / "scalping_zero"

    day_curve = [
        {"ts": "2025-01-01T00:00:00Z", "equity": 0.0},
        {"ts": "2025-01-02T00:00:00Z", "equity": 100200.0},
    ]
    scalping_curve = [
        ["2025-01-01T00:00:00Z", 50000.0],
        ["2025-01-02T00:00:00Z", 50100.0],
    ]

    _write_metrics(
        day_run / "metrics.json",
        {
            "equity_curve": day_curve,
            "runtime": {"execution_health": {"reject_rate": 0.0, "slippage_bps": 1.5}},
        },
    )
    _write_metrics(
        scalping_run / "metrics.json",
        {
            "equity_curve": scalping_curve,
            "runtime": {"execution_health": {"reject_rate": 0.02, "slippage_bps": 2.5}},
        },
    )

    snapshot_dir = tmp_path / "snapshot_zero"
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
        "tokyo_micro_mean_reversion_v0=1",
        "--correlation-window-minutes",
        "240",
        "--indent",
        "2",
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)

    telemetry_path = snapshot_dir / "telemetry.json"
    telemetry = json.loads(telemetry_path.read_text(encoding="utf-8"))
    assert telemetry["execution_health"]["day_orb_5m_v1"]["reject_rate"] == pytest.approx(0.0)

    day_metrics_path = snapshot_dir / "metrics" / "day_orb_5m_v1.json"
    day_payload = json.loads(day_metrics_path.read_text(encoding="utf-8"))
    assert day_payload["equity_curve"][0]["equity"] == pytest.approx(0.0)


def test_build_router_snapshot_cli_uses_router_demo_metrics(tmp_path: Path) -> None:
    snapshot_dir = _build_router_snapshot_from_samples(tmp_path)

    telemetry_path = snapshot_dir / "telemetry.json"
    telemetry = json.loads(telemetry_path.read_text(encoding="utf-8"))

    assert telemetry["active_positions"] == {
        "day_orb_5m_v1": 1,
        "tokyo_micro_mean_reversion_v0": 2,
    }
    assert telemetry["category_utilisation_pct"]["day"] == pytest.approx(0.25, rel=1e-6)
    assert telemetry["category_utilisation_pct"]["scalping"] == pytest.approx(0.08, rel=1e-6)
    assert telemetry["category_budget_headroom_pct"]["day"] == pytest.approx(39.75, rel=1e-6)
    assert telemetry["category_budget_headroom_pct"]["scalping"] == pytest.approx(14.92, rel=1e-6)
    assert telemetry["gross_exposure_pct"] == pytest.approx(0.33, rel=1e-6)
    assert telemetry["gross_exposure_cap_pct"] == pytest.approx(20.0, rel=1e-6)
    assert telemetry["correlation_window_minutes"] == pytest.approx(240.0)
    assert telemetry["execution_health"] == {}

    day_metrics = json.loads(
        (ROUTER_SAMPLE_METRICS / "day_orb_5m_v1.json").read_text(encoding="utf-8")
    )
    scalping_metrics = json.loads(
        (ROUTER_SAMPLE_METRICS / "tokyo_micro_mean_reversion_v0.json").read_text(
            encoding="utf-8"
        )
    )

    curves = {
        "day_orb_5m_v1": build_router_snapshot_module._normalise_curve(
            day_metrics["equity_curve"],
            manifest_id="day_orb_5m_v1",
            source=ROUTER_SAMPLE_METRICS / "day_orb_5m_v1.json",
        ),
        "tokyo_micro_mean_reversion_v0": build_router_snapshot_module._normalise_curve(
            scalping_metrics["equity_curve"],
            manifest_id="tokyo_micro_mean_reversion_v0",
            source=ROUTER_SAMPLE_METRICS / "tokyo_micro_mean_reversion_v0.json",
        ),
    }
    expected_matrix = build_router_snapshot_module._compute_pairwise_correlations(
        curves,
        sources={
            key: ROUTER_SAMPLE_METRICS / f"{key}.json" for key in curves
        },
    )
    expected_corr = expected_matrix["day_orb_5m_v1"]["tokyo_micro_mean_reversion_v0"]
    corr_value = telemetry["strategy_correlations"]["day_orb_5m_v1"][
        "tokyo_micro_mean_reversion_v0"
    ]
    assert corr_value == pytest.approx(expected_corr, rel=1e-6)

    output_day_metrics = json.loads(
        (snapshot_dir / "metrics" / "day_orb_5m_v1.json").read_text(encoding="utf-8")
    )
    output_scalping_metrics = json.loads(
        (snapshot_dir / "metrics" / "tokyo_micro_mean_reversion_v0.json").read_text(
            encoding="utf-8"
        )
    )
    assert output_day_metrics["equity_curve"] == day_metrics["equity_curve"]
    assert output_scalping_metrics["equity_curve"] == scalping_metrics["equity_curve"]
    assert (snapshot_dir / "metrics" / "configs" / "strategies" / "day_orb_5m.yaml").exists()
    assert (
        snapshot_dir
        / "metrics"
        / "configs"
        / "strategies"
        / "tokyo_micro_mean_reversion.yaml"
    ).exists()


def test_build_router_snapshot_help_lists_correlation_window_flag() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/build_router_snapshot.py", "--help"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "--correlation-window-minutes" in result.stdout

def test_report_portfolio_summary_cli_budget_status(tmp_path: Path) -> None:
    snapshot_dir = _build_router_snapshot_from_samples(tmp_path)
    _mutate_budget_headroom(snapshot_dir)

    output_path = tmp_path / "summary.json"
    subprocess.run(
        [
            sys.executable,
            "scripts/report_portfolio_summary.py",
            "--input",
            str(snapshot_dir),
            "--output",
            str(output_path),
            "--indent",
            "2",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    summary = json.loads(output_path.read_text(encoding="utf-8"))
    categories = {row["category"]: row for row in summary["category_utilisation"]}

    day_entry = categories["day"]
    assert day_entry["budget_status"] == "warning"
    assert 0 < day_entry["budget_headroom_pct"] <= 5.0 + 1e-6
    assert "budget_over_pct" not in day_entry

    scalping_entry = categories["scalping"]
    assert scalping_entry["budget_status"] == "breach"
    assert scalping_entry["budget_headroom_pct"] < 0
    assert scalping_entry["budget_over_pct"] == pytest.approx(
        abs(scalping_entry["budget_headroom_pct"])
    )


def test_router_demo_pipeline_cli_budget_escalations(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    build_script = repo_root / "scripts" / "build_router_snapshot.py"
    report_script = repo_root / "scripts" / "report_portfolio_summary.py"

    day_metrics_path, _ = _load_router_demo_metrics("day_orb_5m_v1")
    scalping_metrics_path, _ = _load_router_demo_metrics(
        "tokyo_micro_mean_reversion_v0"
    )

    output_dir = tmp_path / "runs" / "router_pipeline" / "latest"
    cmd = [
        sys.executable,
        str(build_script),
        "--manifest",
        str((repo_root / DAY_MANIFEST).resolve()),
        "--manifest",
        str((repo_root / SCALPING_MANIFEST).resolve()),
        "--manifest-run",
        f"day_orb_5m_v1={day_metrics_path}",
        "--manifest-run",
        f"tokyo_micro_mean_reversion_v0={scalping_metrics_path}",
        "--positions",
        "day_orb_5m_v1=1",
        "--positions",
        "tokyo_micro_mean_reversion_v0=2",
        "--category-budget",
        "day=3.0",
        "--category-budget",
        "scalping=0.05",
        "--correlation-window-minutes",
        "240",
        "--indent",
        "2",
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True, cwd=tmp_path)

    telemetry_path = output_dir / "telemetry.json"
    telemetry = json.loads(telemetry_path.read_text(encoding="utf-8"))

    assert telemetry["category_budget_pct"]["day"] == pytest.approx(3.0)
    assert telemetry["category_budget_pct"]["scalping"] == pytest.approx(0.05)
    assert telemetry["category_utilisation_pct"]["day"] == pytest.approx(0.25, rel=1e-6)
    assert telemetry["category_utilisation_pct"]["scalping"] == pytest.approx(
        0.08, rel=1e-6
    )

    day_headroom = telemetry["category_budget_headroom_pct"]["day"]
    scalping_headroom = telemetry["category_budget_headroom_pct"]["scalping"]
    assert day_headroom == pytest.approx(
        telemetry["category_budget_pct"]["day"]
        - telemetry["category_utilisation_pct"]["day"]
    )
    assert 0 < day_headroom <= 5.0 + 1e-6

    assert scalping_headroom == pytest.approx(
        telemetry["category_budget_pct"]["scalping"]
        - telemetry["category_utilisation_pct"]["scalping"]
    )
    assert scalping_headroom < 0

    summary_output = tmp_path / "portfolio_summary.json"
    summary_cmd = [
        sys.executable,
        str(report_script),
        "--input",
        str(output_dir),
        "--output",
        str(summary_output),
        "--indent",
        "2",
    ]
    subprocess.run(summary_cmd, check=True, capture_output=True, text=True, cwd=tmp_path)

    summary = json.loads(summary_output.read_text(encoding="utf-8"))
    categories = {row["category"]: row for row in summary["category_utilisation"]}

    day_entry = categories["day"]
    assert day_entry["budget_status"] == "warning"
    assert "budget_over_pct" not in day_entry
    assert day_entry["budget_headroom_pct"] == pytest.approx(
        day_entry["budget_pct"] - day_entry["utilisation_pct"]
    )

    scalping_entry = categories["scalping"]
    assert scalping_entry["budget_status"] == "breach"
    assert scalping_entry["budget_over_pct"] == pytest.approx(
        abs(scalping_entry["budget_headroom_pct"])
    )
    assert scalping_entry["budget_headroom_pct"] == pytest.approx(
        scalping_entry["budget_pct"] - scalping_entry["utilisation_pct"]
    )


def test_build_router_snapshot_handles_offset_equity_curves(tmp_path: Path) -> None:
    day_run = tmp_path / "runs" / "day"
    scalping_run = tmp_path / "runs" / "scalping"

    day_curve = [
        ["2025-01-01T00:00:00Z", 100000.0],
        ["2025-01-02T00:00:00Z", 100250.0],
        ["2025-01-03T00:00:00Z", 100450.0],
        ["2025-01-04T00:00:00Z", 100900.0],
        ["2025-01-05T00:00:00Z", 101100.0],
    ]
    scalping_curve = [
        ["2025-01-03T00:00:00Z", 60000.0],
        ["2025-01-04T00:00:00Z", 60300.0],
        ["2025-01-05T00:00:00Z", 60450.0],
    ]

    _write_metrics(
        day_run / "metrics.json",
        {
            "trades": 4,
            "equity_curve": day_curve,
            "runtime": {"execution_health": {"reject_rate": 0.01, "slippage_bps": 3.0}},
        },
    )
    _write_metrics(
        scalping_run / "metrics.json",
        {
            "trades": 2,
            "equity_curve": scalping_curve,
            "runtime": {"execution_health": {"reject_rate": 0.02, "slippage_bps": 5.0}},
        },
    )

    snapshot_dir = tmp_path / "snapshot_offset"
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
        "tokyo_micro_mean_reversion_v0=1",
        "--indent",
        "2",
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)

    telemetry_path = snapshot_dir / "telemetry.json"
    telemetry = json.loads(telemetry_path.read_text(encoding="utf-8"))

    corr_value = telemetry["strategy_correlations"]["day_orb_5m_v1"]["tokyo_micro_mean_reversion_v0"]
    expected_corr = _compute_expected_correlation(
        [point[1] for point in day_curve[-3:]],
        [point[1] for point in scalping_curve],
    )
    assert corr_value == pytest.approx(expected_corr, rel=1e-6)
