import json
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List
from types import SimpleNamespace

import pytest

from scripts import run_param_sweep as sweep
from scripts._param_sweep import SeasonalSlice, load_experiment_config
from core.utils import yaml_compat as yaml


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


def test_load_experiment_config_includes_bayes_section():
    config = load_experiment_config("configs/experiments/day_orb_core.yaml")
    assert config.bayes is not None
    assert config.bayes.enabled is True
    assert config.bayes.initial_random_trials == 16
    assert config.bayes.constraint_retry_limit == 2
    assert config.bayes.acquisition is not None
    assert config.bayes.acquisition.name == "expected_improvement"
    hint = config.bayes.transforms.get("min_or_atr_ratio")
    assert hint is not None
    assert hint.transform == "log"
    assert hint.bounds == (0.15, 0.4)


def test_bayes_runner_retries_and_summary(tmp_path, monkeypatch):
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text("strategy:\n  parameters:\n    k_tp: 1.5\n", encoding="utf-8")
    runs_dir = tmp_path / "runs"
    config_path = tmp_path / "experiment.yaml"
    config_payload: Dict[str, Any] = {
        "manifest_path": str(manifest_path),
        "base_output_dir": str(runs_dir),
        "runner": {"base_cli": []},
        "search_space": {
            "k_tp": {
                "path": "strategy.parameters.k_tp",
                "type": "float_range",
                "min": 1.0,
                "max": 2.0,
                "step": 0.5,
                "precision": 2,
            }
        },
        "constraints": [],
        "seasonal_slices": [],
        "scoring": {},
        "bayes": {
            "enabled": True,
            "seed": 11,
            "initial_random_trials": 1,
            "constraint_retry_limit": 1,
            "transforms": {
                "k_tp": {
                    "mode": "continuous",
                    "transform": "identity",
                }
            },
        },
    }
    config_path.write_text(yaml.safe_dump(config_payload, sort_keys=False), encoding="utf-8")

    outcomes = [
        {"feasible": False, "score": 0.1},
        {"feasible": True, "score": 0.2},
        {"feasible": True, "score": 0.3},
    ]
    call_log: List[Dict[str, Any]] = []

    def fake_run_single(self, spec, trial_dir):
        index = min(len(call_log), len(outcomes) - 1)
        outcome = outcomes[index]
        trial_dir.mkdir(parents=True, exist_ok=True)
        metadata = {
            "trial_id": spec.token,
            "params": spec.params,
            "seed": spec.seed,
            "search": self.args.search,
            "timestamp": self.timestamp,
            "status": "completed",
            "constraints": {},
            "metrics": {"sharpe": outcome["score"]},
            "seasonal": {},
            "feasible": outcome["feasible"],
            "score": outcome["score"],
        }
        if spec.metadata:
            metadata["search_metadata"] = dict(spec.metadata)
        result_path = trial_dir / "result.json"
        sweep._write_json(result_path, metadata)
        call_log.append(metadata)
        return sweep.TrialResult(spec=spec, status="completed", result_path=result_path, payload=metadata)

    monkeypatch.setattr(sweep.SweepRunner, "_run_single", fake_run_single)

    out_dir = tmp_path / "output"
    argv = [
        "--experiment",
        str(config_path),
        "--search",
        "bayes",
        "--max-trials",
        "3",
        "--out",
        str(out_dir),
    ]
    exit_code = sweep.main(argv)
    assert exit_code == 0

    summary_path = out_dir / "sweep_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["search"] == "bayes"
    assert summary["total_trials"] == 3
    bayes_block = summary.get("bayes")
    assert bayes_block is not None
    assert bayes_block["evaluations"] == 3
    assert bayes_block["constraint_retries"] == 1
    assert bayes_block["optuna_available"] is False
    assert "fallback_message" in bayes_block

    results = list(out_dir.glob("*/result.json"))
    assert len(results) == 3
    payloads = [json.loads(path.read_text(encoding="utf-8")) for path in results]
    suggestion_indexes = sorted(entry["search_metadata"]["suggestion_index"] for entry in payloads)
    assert suggestion_indexes[0] == 1
    assert any(entry["search_metadata"].get("retry") == 1 for entry in payloads)
    assert max(suggestion_indexes) >= 2
