from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List

import pytest

from core.utils import yaml_compat as yaml
from scripts import run_target_loop


class _CallCapture:
    def __init__(self) -> None:
        self.commands: List[List[str]] = []
        self.manifest_snapshots: List[Dict[str, Any]] = []

    def __call__(self, cmd: List[str]) -> subprocess.CompletedProcess[str]:
        self.commands.append(list(cmd))
        manifest_idx = cmd.index("--manifest")
        manifest_path = Path(cmd[manifest_idx + 1])
        manifest_data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        assert isinstance(manifest_data, dict)
        self.manifest_snapshots.append(manifest_data)

        metrics_idx = cmd.index("--json-out")
        daily_idx = cmd.index("--out-daily-csv")
        metrics_path = Path(cmd[metrics_idx + 1])
        daily_path = Path(cmd[daily_idx + 1])

        metrics_path.write_text(json.dumps({"total_pips": 1.0}), encoding="utf-8")
        daily_path.write_text("date,breakouts\n2024-01-01,0\n", encoding="utf-8")

        return subprocess.CompletedProcess(cmd, 0, stdout="{}", stderr="")


def test_run_sim_generates_manifest_and_invokes_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    capture = _CallCapture()
    monkeypatch.setattr(run_target_loop, "call", capture)

    base_args = [
        "--manifest",
        "configs/strategies/day_orb_5m.yaml",
        "--csv",
        "validated/USDJPY/5m.csv",
        "--symbol",
        "USDJPY",
        "--mode",
        "conservative",
    ]
    params = {"or_n": 5, "k_tp": 1.1, "k_sl": 0.7, "threshold_lcb": 0.25}
    metrics_path = tmp_path / "metrics.json"
    daily_path = tmp_path / "daily.csv"

    success = run_target_loop.run_sim(base_args, params, metrics_path, daily_path)

    assert success is True
    assert metrics_path.exists()
    assert daily_path.exists()

    assert capture.commands, "expected run_sim to invoke CLI"
    invoked = capture.commands[0]
    manifest_flag = invoked.index("--manifest")
    manifest_path = Path(invoked[manifest_flag + 1])
    assert not manifest_path.exists(), "temporary manifest should be cleaned up"
    assert invoked[invoked.index("--json-out") + 1] == str(metrics_path)
    assert invoked[invoked.index("--out-daily-csv") + 1] == str(daily_path)

    manifest_data = capture.manifest_snapshots[0]
    params_block = manifest_data.get("strategy", {}).get("parameters", {})
    assert params_block.get("or_n") == 5
    assert pytest.approx(params_block.get("k_tp")) == pytest.approx(1.1)
    assert pytest.approx(params_block.get("k_sl")) == pytest.approx(0.7)
    runner_cfg = manifest_data.get("runner", {}).get("runner_config", {})
    runner_cli = manifest_data.get("runner", {}).get("cli_args", {})
    assert pytest.approx(runner_cfg.get("threshold_lcb_pip")) == pytest.approx(0.25)
    assert pytest.approx(runner_cli.get("threshold_lcb")) == pytest.approx(0.25)
