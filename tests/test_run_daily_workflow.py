import sys
from scripts import run_daily_workflow


class DummyResult:
    def __init__(self, returncode=0):
        self.returncode = returncode


def _capture_run_cmd(monkeypatch):
    captured = []

    def fake_run_cmd(cmd):
        captured.append(cmd)
        return DummyResult()

    monkeypatch.setattr(run_daily_workflow, "run_cmd", fake_run_cmd)
    return captured


def test_benchmark_summary_threshold_arguments(monkeypatch):
    captured = _capture_run_cmd(monkeypatch)

    exit_code = run_daily_workflow.main([
        "--benchmark-summary",
        "--min-sharpe", "1.5",
        "--max-drawdown", "250.5",
    ])

    assert exit_code == 0
    assert captured, "run_cmd should be invoked"
    cmd = captured[0]
    assert cmd[0] == sys.executable
    assert "--min-sharpe" in cmd
    assert cmd[cmd.index("--min-sharpe") + 1] == "1.5"
    assert "--max-drawdown" in cmd
    assert cmd[cmd.index("--max-drawdown") + 1] == "250.5"


def test_benchmark_summary_without_thresholds(monkeypatch):
    captured = _capture_run_cmd(monkeypatch)

    exit_code = run_daily_workflow.main(["--benchmark-summary"])

    assert exit_code == 0
    assert captured, "run_cmd should be invoked"
    cmd = captured[0]
    assert "--min-sharpe" not in cmd
    assert "--max-drawdown" not in cmd
