import json
import subprocess
import sys
from pathlib import Path

from core.utils import yaml_compat as yaml

REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_test_config(path: Path, *, base_output: Path) -> None:
    config = {
        "name": "Test Sweep",
        "manifest_path": str(REPO_ROOT / "configs/strategies/day_orb_5m.yaml"),
        "base_output_dir": str(base_output),
        "runner": {"base_cli": []},
        "search_space": {
            "or_n": {
                "path": "strategy.parameters.or_n",
                "type": "choice",
                "values": [4, 6],
            }
        },
        "constraints": [
            {"id": "sharpe_floor", "metric": "metrics.sharpe", "op": ">=", "threshold": 0.0}
        ],
        "scoring": {"objectives": [{"metric": "metrics.sharpe", "goal": "max", "weight": 1.0}]},
    }
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")


def test_run_param_sweep_dry_run(tmp_path):
    config_path = tmp_path / "experiment.yaml"
    out_dir = tmp_path / "sweeps"
    _write_test_config(config_path, base_output=out_dir)
    cmd = [
        sys.executable,
        "scripts/run_param_sweep.py",
        "--experiment",
        str(config_path),
        "--search",
        "grid",
        "--max-trials",
        "2",
        "--dry-run",
        "--out",
        str(out_dir),
    ]
    result = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    summary_path = out_dir / "sweep_summary.json"
    assert summary_path.exists()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["total_trials"] == 2
    trial_dirs = [entry for entry in out_dir.iterdir() if entry.is_dir()]
    assert len(trial_dirs) == 2
    for trial_dir in trial_dirs:
        result_path = trial_dir / "result.json"
        assert result_path.exists()
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        assert payload["status"] == "dry_run"
        assert payload["params"]["or_n"] in {4, 6}
        assert (trial_dir / "manifest.yaml").exists()


def test_select_best_params_ranks_feasible(tmp_path):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    config_path = tmp_path / "experiment.yaml"
    _write_test_config(config_path, base_output=runs_dir)
    # Create two feasible completed trials and one failed trial.
    trial_specs = [
        ("trial_a", 0.6, {"or_n": 4}),
        ("trial_b", 1.2, {"or_n": 6}),
    ]
    for name, sharpe, params in trial_specs:
        trial_dir = runs_dir / name
        trial_dir.mkdir()
        result_payload = {
            "trial_id": name,
            "status": "completed",
            "params": params,
            "metrics": {"sharpe": sharpe, "trades": 10, "wins": 6, "total_pips": 42.0},
            "seasonal": {},
            "command_str": "python -m test",
        }
        (trial_dir / "result.json").write_text(
            json.dumps(result_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    # Add a non-completed trial to ensure it is ignored.
    skipped_dir = runs_dir / "trial_c"
    skipped_dir.mkdir()
    (skipped_dir / "result.json").write_text(
        json.dumps({"trial_id": "trial_c", "status": "failed"}, ensure_ascii=False),
        encoding="utf-8",
    )
    out_path = tmp_path / "best.json"
    cmd = [
        sys.executable,
        "scripts/select_best_params.py",
        "--experiment",
        str(config_path),
        "--runs-dir",
        str(runs_dir),
        "--top-k",
        "1",
        "--out",
        str(out_path),
    ]
    result = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["trials"]["feasible"] == 2
    assert payload["ranking"]
    assert payload["ranking"][0]["trial_id"] == "trial_b"
    assert payload["ranking"][0]["params"]["or_n"] == 6
