"""Tests for scripts.run_benchmark_runs utilities and CLI orchestrator."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator, List

import pytest

from scripts import run_benchmark_runs as rb


def test_filter_window_handles_mixed_timestamp_formats() -> None:
    rows = [
        {"timestamp": "2024-01-01T00:00:00Z", "label": "z"},
        {"timestamp": "2024-01-02 00:00:00", "label": "space"},
        {"timestamp": "2024-01-03T12:34:56.789Z", "label": "fractional"},
        {"timestamp": "2024-01-04T09:00:00+09:00", "label": "offset"},
    ]

    filtered = rb._filter_window(rows, days=2)

    assert filtered == rows[1:]


@pytest.fixture
def benchmark_env(tmp_path: Path) -> dict:
    symbol = "USDJPY"
    mode = "conservative"
    csv_path = tmp_path / "bars.csv"
    csv_lines = [
        "timestamp,symbol,tf,o,h,l,c,v,spread",
        "2024-01-01T00:00:00Z,USDJPY,5m,1,1,1,1,100,0.1",
        "2024-01-02T00:00:00Z,USDJPY,5m,1,1,1,1,110,0.1",
        "2024-01-03T00:00:00Z,USDJPY,5m,1,1,1,1,120,0.1",
    ]
    csv_path.write_text("\n".join(csv_lines) + "\n", encoding="utf-8")

    reports_dir = tmp_path / "reports"
    baseline_dir = reports_dir / "baseline"
    baseline_dir.mkdir(parents=True, exist_ok=True)
    prev_baseline = {
        "trades": 100,
        "wins": 60,
        "total_pips": 250.0,
        "sharpe": 1.1,
        "max_drawdown": -80.0,
    }
    baseline_path = baseline_dir / f"{symbol}_{mode}.json"
    baseline_path.write_text(json.dumps(prev_baseline, ensure_ascii=False), encoding="utf-8")

    snapshot_path = tmp_path / "ops" / "runtime_snapshot.json"
    runs_dir = tmp_path / "runs"

    return {
        "symbol": symbol,
        "mode": mode,
        "csv_path": csv_path,
        "reports_dir": reports_dir,
        "baseline_path": baseline_path,
        "prev_baseline": prev_baseline,
        "snapshot_path": snapshot_path,
        "runs_dir": runs_dir,
    }


def test_main_dry_run_emits_previous_metrics(monkeypatch: pytest.MonkeyPatch, capsys, benchmark_env: dict) -> None:
    def _unexpected_run(*_args, **_kwargs):  # pragma: no cover - guard
        raise AssertionError("subprocess.run should not be invoked during --dry-run")

    monkeypatch.setattr(rb.subprocess, "run", _unexpected_run)

    args = [
        "--bars",
        str(benchmark_env["csv_path"]),
        "--symbol",
        benchmark_env["symbol"],
        "--mode",
        benchmark_env["mode"],
        "--equity",
        "100000",
        "--windows",
        "5,1",
        "--reports-dir",
        str(benchmark_env["reports_dir"]),
        "--snapshot",
        str(benchmark_env["snapshot_path"]),
        "--runs-dir",
        str(benchmark_env["runs_dir"]),
        "--dry-run",
    ]

    rc = rb.main(args)

    captured = capsys.readouterr()
    assert rc == 0
    assert captured.err == ""
    result = json.loads(captured.out)

    expected_win_rate = benchmark_env["prev_baseline"]["wins"] / benchmark_env["prev_baseline"]["trades"]
    assert Path(result["baseline"]) == benchmark_env["baseline_path"]
    assert pytest.approx(result["baseline_metrics"]["win_rate"]) == expected_win_rate
    assert result["alert"] == {"triggered": False}

    windows = [entry["window"] for entry in result["rolling"]]
    assert windows == [5, 1]
    for rolling_entry in result["rolling"]:
        assert rolling_entry["skipped"] is True

    assert not benchmark_env["snapshot_path"].exists()


def test_main_executes_runs_and_updates_outputs(monkeypatch: pytest.MonkeyPatch, capsys, benchmark_env: dict) -> None:
    class DummyProc:
        def __init__(self, returncode: int = 0) -> None:
            self.returncode = returncode

    baseline_metrics = {
        "trades": 120,
        "wins": 96,
        "total_pips": 450.0,
        "sharpe": 1.5,
        "max_drawdown": -40.0,
    }
    rolling_metrics: List[dict] = [
        {"trades": 30, "wins": 22, "total_pips": 90.0, "sharpe": 1.2, "max_drawdown": -20.0},
        {"trades": 12, "wins": 9, "total_pips": 36.0, "sharpe": 0.9, "max_drawdown": -12.0},
    ]
    metrics_iter: Iterator[dict] = iter([baseline_metrics, *rolling_metrics])
    calls: List[List[str]] = []

    def _run(cmd: List[str], check: bool = False):  # noqa: FBT002
        del check
        calls.append(cmd)
        script_name = Path(cmd[1]).name
        if script_name == "run_sim.py":
            metrics = next(metrics_iter)
            json_out = Path(cmd[cmd.index("--json-out") + 1])
            json_out.parent.mkdir(parents=True, exist_ok=True)
            json_out.write_text(json.dumps(metrics, ensure_ascii=False), encoding="utf-8")
            return DummyProc(0)
        if script_name == "rebuild_runs_index.py":
            out_path = Path(cmd[cmd.index("--out") + 1])
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text("run_id,pnl\n", encoding="utf-8")
            return DummyProc(0)
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(rb.subprocess, "run", _run)

    args = [
        "--bars",
        str(benchmark_env["csv_path"]),
        "--symbol",
        benchmark_env["symbol"],
        "--mode",
        benchmark_env["mode"],
        "--equity",
        "100000",
        "--windows",
        "5,1",
        "--reports-dir",
        str(benchmark_env["reports_dir"]),
        "--snapshot",
        str(benchmark_env["snapshot_path"]),
        "--runs-dir",
        str(benchmark_env["runs_dir"]),
        "--alert-pips",
        "10",
        "--alert-winrate",
        "0.01",
    ]

    rc = rb.main(args)

    captured = capsys.readouterr()
    assert rc == 0
    assert captured.err == ""
    result = json.loads(captured.out)

    baseline_path = benchmark_env["baseline_path"]
    assert baseline_path.read_text(encoding="utf-8") == json.dumps(baseline_metrics, ensure_ascii=False)

    expected_win_rate = baseline_metrics["wins"] / baseline_metrics["trades"]
    assert pytest.approx(result["baseline_metrics"]["win_rate"]) == expected_win_rate

    assert result["alert"]["triggered"] is True
    payload = result["alert"]["payload"]
    assert pytest.approx(payload["deltas"]["delta_total_pips"]) == baseline_metrics["total_pips"] - benchmark_env["prev_baseline"]["total_pips"]
    assert pytest.approx(payload["deltas"]["delta_win_rate"]) == expected_win_rate - (
        benchmark_env["prev_baseline"]["wins"] / benchmark_env["prev_baseline"]["trades"]
    )

    rolling_entries = result["rolling"]
    assert [entry["window"] for entry in rolling_entries] == [5, 1]
    for metrics, entry in zip(rolling_metrics, rolling_entries, strict=True):
        json_path = Path(entry["path"])
        assert json.loads(json_path.read_text(encoding="utf-8")) == metrics

    snapshot_data = json.loads(benchmark_env["snapshot_path"].read_text(encoding="utf-8"))
    key = f"{benchmark_env['symbol']}_{benchmark_env['mode']}"
    assert snapshot_data["benchmarks"][key] == result["latest_ts"]
    assert result["runs_index_rc"] == 0

    run_sim_calls = [Path(cmd[1]).name for cmd in calls if Path(cmd[1]).name == "run_sim.py"]
    assert len(run_sim_calls) == 3


def test_main_propagates_run_failure(monkeypatch: pytest.MonkeyPatch, capsys, benchmark_env: dict) -> None:
    class DummyProc:
        def __init__(self, returncode: int = 0) -> None:
            self.returncode = returncode

    calls: List[List[str]] = []

    def _run(cmd: List[str], check: bool = False):  # noqa: FBT002
        del check
        calls.append(cmd)
        script_name = Path(cmd[1]).name
        if script_name == "run_sim.py":
            return DummyProc(2)
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(rb.subprocess, "run", _run)

    args = [
        "--bars",
        str(benchmark_env["csv_path"]),
        "--symbol",
        benchmark_env["symbol"],
        "--mode",
        benchmark_env["mode"],
        "--equity",
        "100000",
        "--windows",
        "5,1",
        "--reports-dir",
        str(benchmark_env["reports_dir"]),
        "--snapshot",
        str(benchmark_env["snapshot_path"]),
        "--runs-dir",
        str(benchmark_env["runs_dir"]),
    ]

    rc = rb.main(args)

    captured = capsys.readouterr()
    assert rc == 2
    assert captured.out == ""
    assert captured.err == ""

    assert benchmark_env["baseline_path"].read_text(encoding="utf-8") == json.dumps(
        benchmark_env["prev_baseline"], ensure_ascii=False
    )
    assert not benchmark_env["snapshot_path"].exists()
    assert len(calls) == 1
