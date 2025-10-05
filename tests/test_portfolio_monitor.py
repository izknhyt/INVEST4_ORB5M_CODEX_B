import json
import subprocess
import sys
from pathlib import Path

import pytest

from analysis.portfolio_monitor import build_portfolio_summary

FIXTURE_DIR = Path("reports/portfolio_samples/router_demo")


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
