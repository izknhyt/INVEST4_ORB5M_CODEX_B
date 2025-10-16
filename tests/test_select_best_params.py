import json
import subprocess
import sys
from pathlib import Path

from core.utils import yaml_compat as yaml

REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_test_config(path: Path, *, base_output: Path) -> None:
    config = {
        "name": "Select Best Params Test",
        "manifest_path": str(REPO_ROOT / "configs/strategies/day_orb_5m.yaml"),
        "base_output_dir": str(base_output),
        "runner": {
            "base_cli": ["--csv", "validated/USDJPY/5m.csv"],
            "equity": 100000,
        },
        "search_space": {
            "or_n": {
                "path": "strategy.parameters.or_n",
                "type": "choice",
                "values": [4, 6],
            }
        },
        "constraints": [
            {"id": "sharpe_floor", "metric": "metrics.sharpe", "op": ">=", "threshold": 0.0},
            {"id": "trades_per_month_floor", "metric": "metrics.trades_per_month", "op": ">=", "threshold": 10},
            {"id": "seasonal_2024_h1", "metric": "seasonal.2024_h1.sharpe", "op": ">=", "threshold": -0.2},
        ],
        "seasonal_slices": [
            {"id": "2024_h1", "start": "2024-01-01", "end": "2024-06-30"}
        ],
        "scoring": {
            "objectives": [
                {"metric": "metrics.sharpe", "goal": "max", "weight": 1.0},
                {"metric": "metrics.total_pips", "goal": "max", "weight": 0.02},
            ],
            "penalties": [],
            "tie_breakers": [
                {"metric": "metrics.total_pips", "goal": "max"}
            ],
        },
    }
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")


def _write_trial(directory: Path, trial_id: str, sharpe: float, total_pips: float, trades_per_month: float) -> None:
    directory.mkdir()
    payload = {
        "trial_id": trial_id,
        "status": "completed",
        "params": {"or_n": 4},
        "metrics": {
            "sharpe": sharpe,
            "total_pips": total_pips,
            "trades_per_month": trades_per_month,
        },
        "seasonal": {"2024_h1": {"sharpe": 0.1}},
        "metrics_path": f"runs/{trial_id}/metrics.json",
        "dataset": {"path": "validated/USDJPY/5m.csv", "sha256": "abc", "rows": 579578},
    }
    (directory / "result.json").write_text(json.dumps(payload), encoding="utf-8")


def test_select_best_params_pareto_filter(tmp_path):
    config_path = tmp_path / "experiment.yaml"
    runs_dir = tmp_path / "runs"
    out_path = tmp_path / "best.json"
    runs_dir.mkdir()
    _write_test_config(config_path, base_output=runs_dir)

    _write_trial(runs_dir / "trial_a", "trial_a", sharpe=1.0, total_pips=40.0, trades_per_month=18.0)
    _write_trial(runs_dir / "trial_b", "trial_b", sharpe=0.85, total_pips=60.0, trades_per_month=20.0)
    _write_trial(runs_dir / "trial_c", "trial_c", sharpe=0.5, total_pips=20.0, trades_per_month=15.0)

    cmd = [
        sys.executable,
        "scripts/select_best_params.py",
        "--experiment",
        str(config_path),
        "--runs-dir",
        str(runs_dir),
        "--top-k",
        "3",
        "--out",
        str(out_path),
    ]
    result = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["trials"]["completed"] == 3
    assert payload["trials"]["feasible"] == 3
    assert payload["trials"]["pareto"] == 2
    ranking_ids = [entry["trial_id"] for entry in payload["ranking"]]
    assert set(ranking_ids) == {"trial_a", "trial_b"}
    for entry in payload["ranking"]:
        assert "rank" in entry
        assert entry["pareto_optimal"] is True
        assert entry["metrics_path"].endswith("metrics.json")
        assert entry["dataset_fingerprint"]["path"] == "validated/USDJPY/5m.csv"
    assert "trial_c" not in ranking_ids
