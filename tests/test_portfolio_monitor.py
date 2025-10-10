import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, Tuple

import pytest

from analysis.portfolio_monitor import build_portfolio_summary

FIXTURE_DIR = Path("reports/portfolio_samples/router_demo")


def _override_manifest_name(path: Path, new_name: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    updated = []
    replaced = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("name:") and not replaced:
            indent = line[: len(line) - len(line.lstrip())]
            updated.append(f"{indent}name: {new_name}")
            replaced = True
        else:
            updated.append(line)
    if not replaced:
        raise AssertionError(f"name field not found in {path}")
    path.write_text("\n".join(updated) + "\n", encoding="utf-8")


def _prepare_snapshot(tmp_path: Path) -> Tuple[Path, Dict[str, str]]:
    repo_root = Path(__file__).resolve().parents[1]
    sample_dir = repo_root / "reports" / "portfolio_samples" / "router_demo"
    snapshot_dir = tmp_path / "snapshot"
    shutil.copytree(sample_dir, snapshot_dir)

    metrics_dir = snapshot_dir / "metrics"
    sentinel_names: Dict[str, str] = {}
    for metrics_file in metrics_dir.glob("*.json"):
        payload = json.loads(metrics_file.read_text(encoding="utf-8"))
        manifest_relative = Path(payload["manifest_path"])
        manifest_src = repo_root / manifest_relative
        manifest_dest = metrics_file.parent / manifest_relative
        manifest_dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(manifest_src, manifest_dest)
        new_name = f"TEMP::{manifest_dest.stem}"
        _override_manifest_name(manifest_dest, new_name)
        sentinel_names[payload["manifest_id"]] = new_name
    return snapshot_dir, sentinel_names


def _update_snapshot_telemetry(
    snapshot_dir: Path,
    *,
    utilisation_updates: Dict[str, float],
    headroom_updates: Dict[str, float],
) -> None:
    telemetry_path = snapshot_dir / "telemetry.json"
    payload = json.loads(telemetry_path.read_text(encoding="utf-8"))
    payload.setdefault("category_utilisation_pct", {}).update(utilisation_updates)
    payload.setdefault("category_budget_headroom_pct", {}).update(headroom_updates)
    telemetry_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


@pytest.mark.parametrize("base_dir", [FIXTURE_DIR])
def test_build_portfolio_summary_returns_expected_sections(base_dir: Path) -> None:
    summary = build_portfolio_summary(base_dir)

    categories = {item["category"]: item for item in summary["category_utilisation"]}
    assert categories["day"]["utilisation_pct"] == pytest.approx(18.75, rel=1e-6)
    assert categories["day"]["headroom_pct"] == pytest.approx(21.25, rel=1e-6)
    assert categories["scalping"]["utilisation_pct"] == pytest.approx(12.08, rel=1e-6)
    assert categories["scalping"]["headroom_pct"] == pytest.approx(2.92, rel=1e-6)

    gross = summary["gross_exposure"]
    assert gross["current_pct"] == 30.5
    assert gross["headroom_pct"] == pytest.approx(24.5, rel=1e-6)

    heatmap = {(row["source"], row["target"]): row["correlation"] for row in summary["correlation_heatmap"]}
    assert heatmap[("day_orb_5m_v1", "tokyo_micro_mean_reversion_v0")] == pytest.approx(0.42, rel=1e-6)

    aggregate_dd = summary["drawdowns"]["aggregate"]["max_drawdown_pct"]
    assert aggregate_dd == pytest.approx(0.3137, rel=1e-3)

    assert "execution_health" in summary
    assert summary["execution_health"]["day_orb_5m_v1"]["reject_rate"] == pytest.approx(0.012, rel=1e-6)


def test_report_portfolio_summary_cli(tmp_path: Path) -> None:
    output_path = tmp_path / "summary.json"
    cmd = [
        sys.executable,
        "scripts/report_portfolio_summary.py",
        "--input",
        str(FIXTURE_DIR),
        "--output",
        str(output_path),
        "--indent",
        "2",
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)

    assert output_path.exists()
    with output_path.open() as handle:
        payload = json.load(handle)
    assert payload["input_dir"].endswith(str(FIXTURE_DIR))


def test_portfolio_summary_resolves_relative_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot_dir, sentinel_names = _prepare_snapshot(tmp_path)

    working_dir = tmp_path / "workdir"
    working_dir.mkdir()
    monkeypatch.chdir(working_dir)

    summary = build_portfolio_summary(snapshot_dir)
    resolved = {item["manifest_id"]: item["name"] for item in summary["strategies"]}
    assert resolved == sentinel_names

    output_path = working_dir / "summary.json"
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "report_portfolio_summary.py"
    cmd = [
        sys.executable,
        str(script_path),
        "--input",
        str(snapshot_dir),
        "--output",
        str(output_path),
        "--indent",
        "0",
    ]
    subprocess.run(cmd, check=True, cwd=working_dir)
    script_summary = json.loads(output_path.read_text(encoding="utf-8"))
    script_resolved = {item["manifest_id"]: item["name"] for item in script_summary["strategies"]}
    assert script_resolved == sentinel_names


def test_build_portfolio_summary_reports_budget_status(tmp_path: Path) -> None:
    snapshot_dir, _ = _prepare_snapshot(tmp_path)
    _update_snapshot_telemetry(
        snapshot_dir,
        utilisation_updates={"day": 31.0, "scalping": 16.0},
        headroom_updates={"day": 4.0, "scalping": -1.0},
    )

    summary = build_portfolio_summary(snapshot_dir)
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
