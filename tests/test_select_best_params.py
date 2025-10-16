import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

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
        "portfolio": {
            "strategies": [
                {
                    "id": "day_orb_5m_v1",
                    "use_trial_manifest": True,
                    "use_trial_metrics": True,
                    "position": 1,
                }
            ],
            "var": {"confidence": 0.95},
            "constraints": [
                {
                    "id": "portfolio_var_cap",
                    "metric": "portfolio.var.portfolio_pct",
                    "op": "<=",
                    "threshold": 0.05,
                }
            ],
        },
    }
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")


def _write_trial(
    directory: Path,
    trial_id: str,
    sharpe: float,
    total_pips: float,
    trades_per_month: float,
    *,
    portfolio_pct: float = 0.02,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
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
        "portfolio": {"var": {"portfolio_pct": portfolio_pct}},
    }
    if extra:
        payload.update(extra)
    (directory / "result.json").write_text(json.dumps(payload), encoding="utf-8")


def test_select_best_params_pareto_filter(tmp_path):
    config_path = tmp_path / "experiment.yaml"
    runs_dir = tmp_path / "runs"
    out_path = tmp_path / "best.json"
    runs_dir.mkdir()
    portfolio_dir = tmp_path / "portfolio_exports"
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
        "--portfolio-out",
        str(portfolio_dir),
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
        assert entry["portfolio"]["var"]["portfolio_pct"] <= 0.05
    assert "trial_c" not in ranking_ids

    stdout_payload = json.loads(result.stdout.strip())
    assert "portfolio_output" in stdout_payload
    portfolio_path = Path(stdout_payload["portfolio_output"])
    assert portfolio_path.exists()
    portfolio_payload = json.loads(portfolio_path.read_text(encoding="utf-8"))
    assert portfolio_payload["ranking"][0]["portfolio"]["var"]["portfolio_pct"] <= 0.05
    assert portfolio_payload["ranking"][0]["constraints_summary"]["failed"] == []


def test_select_best_params_preserves_bayes_metadata(tmp_path):
    config_path = tmp_path / "experiment.yaml"
    runs_dir = tmp_path / "runs"
    out_path = tmp_path / "best.json"
    runs_dir.mkdir()
    _write_test_config(config_path, base_output=runs_dir)

    bayes_extra = {
        "search_metadata": {
            "strategy": "bayes",
            "suggestion_index": 2,
            "retry": 1,
            "optimizer": "heuristic",
        },
        "history": {"logged": True, "command": ["python", "scripts/run_sim.py"]},
    }
    _write_trial(
        runs_dir / "bayes_trial",
        "bayes_trial",
        sharpe=1.2,
        total_pips=50.0,
        trades_per_month=19.0,
        extra=bayes_extra,
    )

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
    assert payload["ranking"]
    entry = payload["ranking"][0]
    assert entry["trial_id"] == "bayes_trial"
    assert entry["params"]["or_n"] == 4
    assert entry["search_metadata"]["strategy"] == "bayes"
    assert entry["search_metadata"]["retry"] == 1
    assert "portfolio" in entry
    assert entry["history"]["logged"] is True
    stdout_payload = json.loads(result.stdout.strip())
    assert "portfolio_output" in stdout_payload
    portfolio_path = REPO_ROOT / Path(stdout_payload["portfolio_output"])
    assert portfolio_path.exists()
    portfolio_data = json.loads(portfolio_path.read_text(encoding="utf-8"))
    assert portfolio_data["experiment"] == payload["experiment"]
    assert portfolio_data["ranking"][0]["trial_id"] == "bayes_trial"
    assert portfolio_data["ranking"][0]["portfolio"]["var"]["portfolio_pct"] == pytest.approx(0.02)
    shutil.rmtree(portfolio_path.parent)
    day_orb_dir = portfolio_path.parent.parent
    if day_orb_dir.exists() and not any(day_orb_dir.iterdir()):
        day_orb_dir.rmdir()
