from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from analysis.dashboard import (
    load_ev_history,
    load_state_slippage,
    load_turnover_metrics,
)


ARCHIVE_DIR = Path("ops/state_archive/day_orb_5m.DayORB5m/USDJPY/conservative")
RUNS_ROOT = Path("runs")
TELEMETRY_PATH = Path("reports/portfolio_samples/router_demo/telemetry.json")


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
    out_path = tmp_path / "dashboard.json"
    cmd = [
        sys.executable,
        "analysis/export_dashboard_data.py",
        "--out-json",
        str(out_path),
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
        "--ev-limit",
        "10",
        "--slip-limit",
        "5",
        "--turnover-limit",
        "5",
        "--indent",
        "0",
    ]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    assert out_path.exists()
    payload = json.loads(out_path.read_text())
    assert payload["ev_history"], "EV history missing from payload"
    assert payload["slippage"]["state"], "State slippage missing"
    assert "turnover" in payload and isinstance(payload["turnover"], list)
    latest = payload.get("win_rate_lcb", {}).get("latest")
    assert latest and latest.get("win_rate_lcb") is not None
    assert result.stdout.strip(), "CLI should report output path"
