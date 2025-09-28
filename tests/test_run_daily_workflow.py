import sys
from pathlib import Path

import pytest

from scripts import run_daily_workflow


def _capture_run_cmd(monkeypatch):
    captured = []

    def fake_run_cmd(cmd):
        captured.append(cmd)
        return 0

    monkeypatch.setattr(run_daily_workflow, "run_cmd", fake_run_cmd)
    return captured


def _assert_path_arg(cmd, flag, expected_path):
    value = cmd[cmd.index(flag) + 1]
    assert Path(value) == Path(expected_path)


@pytest.fixture
def failing_run_cmd(monkeypatch):
    captured = []
    failure_code = 7

    def fake_run_cmd(cmd):
        captured.append(cmd)
        return failure_code

    monkeypatch.setattr(run_daily_workflow, "run_cmd", fake_run_cmd)
    return captured, failure_code


def test_benchmark_summary_threshold_arguments(monkeypatch):
    captured = _capture_run_cmd(monkeypatch)

    exit_code = run_daily_workflow.main([
        "--benchmark-summary",
        "--min-sharpe", "1.5",
        "--max-drawdown", "250.5",
        "--benchmark-windows", "400,200",
    ])

    assert exit_code == 0
    assert captured, "run_cmd should be invoked"
    cmd = captured[0]
    assert cmd[0] == sys.executable
    assert "--min-sharpe" in cmd
    assert cmd[cmd.index("--min-sharpe") + 1] == "1.5"
    assert "--max-drawdown" in cmd
    assert cmd[cmd.index("--max-drawdown") + 1] == "250.5"
    assert "--windows" in cmd
    assert cmd[cmd.index("--windows") + 1] == "400,200"


def test_benchmark_summary_without_thresholds(monkeypatch):
    captured = _capture_run_cmd(monkeypatch)

    exit_code = run_daily_workflow.main(["--benchmark-summary"])

    assert exit_code == 0
    assert captured, "run_cmd should be invoked"
    cmd = captured[0]
    assert "--min-sharpe" not in cmd
    assert "--max-drawdown" not in cmd
    assert cmd[cmd.index("--windows") + 1] == "365,180,90"


def test_benchmark_summary_with_webhook(monkeypatch):
    captured = _capture_run_cmd(monkeypatch)

    exit_code = run_daily_workflow.main([
        "--benchmark-summary",
        "--webhook",
        "https://example.com/summary",
        "--benchmark-windows",
        "120,30",
    ])

    assert exit_code == 0
    assert captured, "run_cmd should be invoked"
    cmd = captured[0]
    assert "--webhook" in cmd
    assert cmd[cmd.index("--webhook") + 1] == "https://example.com/summary"
    assert cmd[cmd.index("--windows") + 1] == "120,30"


def test_benchmarks_pipeline_arguments(monkeypatch):
    captured = _capture_run_cmd(monkeypatch)

    exit_code = run_daily_workflow.main([
        "--benchmarks",
        "--symbol", "GBPJPY",
        "--mode", "bridge",
        "--equity", "250000",
        "--alert-pips", "110",
        "--alert-winrate", "0.2",
        "--min-sharpe", "1.0",
        "--max-drawdown", "150",
        "--webhook", "https://example.com/hook",
        "--benchmark-windows", "200,60",
    ])

    assert exit_code == 0
    cmd = captured[0]
    assert cmd[0] == sys.executable
    assert "run_benchmark_pipeline.py" in cmd[1]
    assert cmd[cmd.index("--symbol") + 1] == "GBPJPY"
    assert cmd[cmd.index("--mode") + 1] == "bridge"
    assert cmd[cmd.index("--equity") + 1] == "250000"
    assert float(cmd[cmd.index("--alert-pips") + 1]) == pytest.approx(110.0)
    assert float(cmd[cmd.index("--alert-winrate") + 1]) == pytest.approx(0.2)
    assert float(cmd[cmd.index("--min-sharpe") + 1]) == pytest.approx(1.0)
    assert float(cmd[cmd.index("--max-drawdown") + 1]) == pytest.approx(150.0)
    assert cmd[cmd.index("--webhook") + 1] == "https://example.com/hook"
    assert cmd[cmd.index("--windows") + 1] == "200,60"


def test_optimize_uses_absolute_paths(monkeypatch):
    captured = _capture_run_cmd(monkeypatch)

    exit_code = run_daily_workflow.main(["--optimize"])

    assert exit_code == 0
    assert captured, "run_cmd should be invoked"
    cmd = captured[0]
    root = run_daily_workflow.ROOT
    _assert_path_arg(cmd, "--csv", root / "data/usdjpy_5m_2018-2024_utc.csv")
    _assert_path_arg(cmd, "--report", root / "reports/auto_optimize.json")


def test_analyze_latency_uses_absolute_paths(monkeypatch):
    captured = _capture_run_cmd(monkeypatch)

    exit_code = run_daily_workflow.main(["--analyze-latency"])

    assert exit_code == 0
    assert captured, "run_cmd should be invoked"
    cmd = captured[0]
    root = run_daily_workflow.ROOT
    _assert_path_arg(cmd, "--input", root / "ops/signal_latency.csv")
    _assert_path_arg(cmd, "--json-out", root / "reports/signal_latency.json")


def test_archive_state_uses_absolute_paths(monkeypatch):
    captured = _capture_run_cmd(monkeypatch)

    exit_code = run_daily_workflow.main(["--archive-state"])

    assert exit_code == 0
    assert captured, "run_cmd should be invoked"
    cmd = captured[0]
    root = run_daily_workflow.ROOT
    _assert_path_arg(cmd, "--runs-dir", root / "runs")
    _assert_path_arg(cmd, "--output", root / "ops/state_archive")


def test_main_returns_first_failure(failing_run_cmd):
    captured, failure_code = failing_run_cmd

    exit_code = run_daily_workflow.main(["--benchmarks", "--benchmark-summary"])

    assert exit_code == failure_code
    assert len(captured) == 1
