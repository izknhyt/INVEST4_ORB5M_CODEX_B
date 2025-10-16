import json
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import run_param_sweep as sweep
from scripts._param_sweep import SeasonalSlice


@pytest.mark.usefixtures("tmp_path")
def test_write_sweep_log_records_success_and_failure(tmp_path):
    config = SimpleNamespace(identifier="test_experiment", path=Path("configs/experiments/day_orb_core.yaml"))
    pass_dir = tmp_path / "trial_pass"
    fail_dir = tmp_path / "trial_fail"
    pass_dir.mkdir()
    fail_dir.mkdir()
    pass_payload = {
        "trial_id": "trial_pass",
        "status": "completed",
        "feasible": True,
        "constraints": {
            "sharpe_floor": {"status": "pass"},
            "trades_per_month_floor": {"status": "pass"},
        },
        "score": 1.23,
        "metrics_path": "runs/trial_pass/metrics.json",
        "dataset": {"path": "validated/USDJPY/5m.csv", "sha256": "abc", "rows": 10},
    }
    fail_payload = {
        "trial_id": "trial_fail",
        "status": "completed",
        "constraints": {
            "sharpe_floor": {"status": "fail"},
            "trades_per_month_floor": {"status": "pass"},
        },
        "score": -0.1,
        "metrics_path": "runs/trial_fail/metrics.json",
        "dataset": {"path": "validated/USDJPY/5m.csv", "sha256": "abc", "rows": 10},
    }
    (pass_dir / "result.json").write_text(json.dumps(pass_payload), encoding="utf-8")
    (fail_dir / "result.json").write_text(json.dumps(fail_payload), encoding="utf-8")

    sweep._write_sweep_log(config, tmp_path)

    log_path = tmp_path / "log.json"
    assert log_path.exists()
    payload = json.loads(log_path.read_text(encoding="utf-8"))
    assert payload["summary"]["completed"] == 2
    assert payload["summary"]["success"] == 1
    assert payload["summary"]["violations"] == 1
    entries = {entry["trial_id"]: entry for entry in payload["entries"]}
    assert entries["trial_pass"]["failed_constraints"] == []
    assert entries["trial_fail"]["failed_constraints"] == ["sharpe_floor"]
    assert entries["trial_pass"]["dataset"]["path"] == "validated/USDJPY/5m.csv"


def test_compute_seasonal_metrics_filters_ranges(monkeypatch):
    original_pd_module = sweep.pd
    original_sys_entry = sys.modules.get("pandas")
    try:
        if "pandas" in sys.modules:
            sys.modules.pop("pandas")
        pd = pytest.importorskip("pandas")
    finally:
        if original_sys_entry is not None:
            sys.modules["pandas"] = original_sys_entry
    sweep.pd = pd
    try:
        slices = [
            SeasonalSlice.from_dict({"id": "2024_h1", "start": "2024-01-01", "end": "2024-06-30"}),
            SeasonalSlice.from_dict({"id": "2024_h2", "start": "2024-07-01", "end": "2024-12-31"}),
        ]
        daily = pd.DataFrame(
            {
                "date": ["2024-01-05", "2024-03-10", "2024-07-15"],
                "pnl_pips": [10.0, -5.0, 15.0],
                "fills": [1, 1, 1],
                "wins": [1, 0, 1],
            }
        )
        metrics = sweep._compute_seasonal_metrics(daily, slices, equity=None, years_from_data=False)
    finally:
        sweep.pd = original_pd_module
    assert metrics["2024_h1"]["total_pips"] == pytest.approx(5.0)
    assert metrics["2024_h2"]["total_pips"] == pytest.approx(15.0)
    assert "2024_h1" in metrics and "2024_h2" in metrics
