from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import compare_metrics as compare_module


def run_cli(tmp_path: Path, args: list[str]) -> subprocess.CompletedProcess:
    cmd = [
        sys.executable,
        str(Path(compare_module.__file__).resolve()),
        *args,
    ]
    return subprocess.run(cmd, check=True, capture_output=True, text=True, cwd=tmp_path)


def test_compare_metrics_reports_no_differences(tmp_path: Path):
    left = {"trades": 10, "wins": 5, "debug": {"ev_bypass": 0}}
    result = compare_module.compare_metrics(
        left,
        left,
        left_path=Path("left.json"),
        right_path=Path("right.json"),
    )

    assert not result.differences
    assert not result.missing_in_left
    assert not result.missing_in_right
    assert not result.significant_differences


def test_compare_metrics_detects_numeric_difference(tmp_path: Path):
    left = {"trades": 10, "wins": 5}
    right = {"trades": 11, "wins": 5}

    result = compare_module.compare_metrics(
        left,
        right,
        left_path=Path("left.json"),
        right_path=Path("right.json"),
        abs_tolerance=0.0,
        rel_tolerance=0.0,
    )

    assert result.significant_differences
    diff = result.significant_differences[0]
    assert diff.key == "trades"
    assert diff.abs_delta == pytest.approx(1.0)
    assert not diff.within_tolerance


def test_compare_metrics_honours_tolerance(tmp_path: Path):
    left = {"total_pips": 100.0}
    right = {"total_pips": 100.0004}

    result = compare_module.compare_metrics(
        left,
        right,
        left_path=Path("left.json"),
        right_path=Path("right.json"),
        abs_tolerance=0.001,
        rel_tolerance=0.0,
    )

    assert result.differences
    diff = result.differences[0]
    assert diff.within_tolerance
    assert not result.significant_differences


def test_compare_metrics_handles_missing_keys():
    left = {"trades": 10}
    right = {"wins": 5}

    result = compare_module.compare_metrics(
        left,
        right,
        left_path=Path("left.json"),
        right_path=Path("right.json"),
    )

    assert "trades" in result.missing_in_right
    assert "wins" in result.missing_in_left
    assert result.significant_differences == []


def test_cli_outputs_diff_and_exit_code(tmp_path: Path):
    left_path = tmp_path / "baseline.json"
    right_path = tmp_path / "candidate.json"
    left_path.write_text(json.dumps({"trades": 10, "state_loaded": "a"}), encoding="utf-8")
    right_path.write_text(json.dumps({"trades": 11, "state_loaded": "b"}), encoding="utf-8")

    args = [
        "--left",
        str(left_path),
        "--right",
        str(right_path),
        "--ignore",
        "state_loaded",
        "--abs-tol",
        "0.0",
    ]

    with pytest.raises(subprocess.CalledProcessError) as excinfo:
        run_cli(tmp_path, args)

    stderr = excinfo.value.stderr
    stdout = excinfo.value.stdout
    assert "Differences:" in stdout
    assert "trades" in stdout
    assert "Metrics comparison" not in stderr
    before_differences, _, after_differences = stdout.partition("Differences:")
    assert "state_loaded" in before_differences
    assert "state_loaded" not in after_differences
