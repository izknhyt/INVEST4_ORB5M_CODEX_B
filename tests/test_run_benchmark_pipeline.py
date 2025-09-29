"""Tests for scripts.run_benchmark_pipeline orchestration."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Iterator, List

import pytest

from scripts import run_benchmark_pipeline as rbp


class DummyCompletedProcess:
    def __init__(self, cmd: List[str], *, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.args = cmd
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


AGGREGATE_SUCCESS: Dict[str, object] = {"returncode": 0, "error": ""}


def _write_metrics(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_pipeline_success_updates_snapshot(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys) -> None:
    baseline_path = tmp_path / "reports" / "baseline" / "USDJPY_conservative.json"
    _write_metrics(
        baseline_path,
        {
            "sharpe": 1.0,
            "max_drawdown": -70.0,
            "win_rate": 0.6,
            "aggregate_ev": AGGREGATE_SUCCESS,
        },
    )

    benchmark_payload = {
        "baseline": str(baseline_path),
        "baseline_metrics": {
            "trades": 100,
            "wins": 60,
            "total_pips": 250.0,
            "win_rate": 0.6,
            "sharpe": 1.0,
            "max_drawdown": -70.0,
        },
        "rolling": [
            {"window": 365, "path": str(tmp_path / "reports" / "rolling" / "365" / "USDJPY_conservative.json")},
            {"window": 180, "path": str(tmp_path / "reports" / "rolling" / "180" / "USDJPY_conservative.json")},
            {"window": 90, "path": str(tmp_path / "reports" / "rolling" / "90" / "USDJPY_conservative.json")},
        ],
        "latest_ts": "2024-06-10T00:00:00",
        "alert": {
            "triggered": True,
            "payload": {
                "event": "benchmark_shift",
                "symbol": "USDJPY",
                "mode": "conservative",
                "timestamp": "2024-06-10T00:10:00Z",
                "thresholds": {
                    "total_pips": 75.0,
                    "win_rate": 0.12,
                    "sharpe": 0.22,
                    "max_drawdown": 55.0,
                },
                "metrics_prev": {"sharpe": 1.4, "max_drawdown": -40.0},
                "metrics_new": {"sharpe": 1.0, "max_drawdown": -90.0},
                "deltas": {
                    "delta_total_pips": -120.0,
                    "delta_win_rate": -0.08,
                    "delta_sharpe": -0.4,
                    "delta_max_drawdown": -50.0,
                },
                "report_path": str(baseline_path),
            },
        },
    }
    summary_payload = {
        "generated_at": "2024-06-10T01:00:00Z",
        "symbol": "USDJPY",
        "mode": "conservative",
        "baseline": {
            "trades": 100,
            "wins": 60,
            "win_rate": 0.6,
            "total_pips": 250.0,
            "sharpe": 1.1,
            "max_drawdown": -70.0,
        },
        "rolling": [],
        "warnings": ["baseline total_pips negative: -10.0"],
        "webhook": {"deliveries": [{"url": "https://example.com/hook", "ok": True, "detail": "status=200"}]},
    }

    # Prepare rolling output files with required metrics
    for entry in benchmark_payload["rolling"]:
        rolling_path = Path(entry["path"])
        _write_metrics(
            rolling_path,
            {
                "win_rate": 0.58,
                "sharpe": 1.2,
                "max_drawdown": -55.0,
                "aggregate_ev": AGGREGATE_SUCCESS,
            },
        )

    commands: List[List[str]] = []
    results: Iterator[DummyCompletedProcess] = iter([
        DummyCompletedProcess([], returncode=0, stdout=json.dumps(benchmark_payload)),
        DummyCompletedProcess([], returncode=0, stdout=json.dumps(summary_payload)),
    ])

    def fake_run(cmd: List[str], /) -> DummyCompletedProcess:
        commands.append(cmd)
        try:
            result = next(results)
        except StopIteration:  # pragma: no cover - guard
            raise AssertionError("unexpected extra subprocess invocation")
        result.args = cmd
        if "report_benchmark_summary.py" in Path(cmd[1]).name:
            json_out = Path(cmd[cmd.index("--json-out") + 1])
            json_out.parent.mkdir(parents=True, exist_ok=True)
            json_out.write_text(json.dumps(summary_payload, ensure_ascii=False), encoding="utf-8")
        return result

    monkeypatch.setattr(rbp, "_run_subprocess", fake_run)

    snapshot_path = tmp_path / "ops" / "runtime_snapshot.json"
    args = [
        "--bars",
        str(tmp_path / "bars.csv"),
        "--symbol",
        "USDJPY",
        "--mode",
        "conservative",
        "--equity",
        "100000",
        "--runs-dir",
        str(tmp_path / "runs"),
        "--reports-dir",
        str(tmp_path / "reports"),
        "--snapshot",
        str(snapshot_path),
        "--summary-json",
        str(tmp_path / "reports" / "benchmark_summary.json"),
        "--summary-plot",
        str(tmp_path / "reports" / "benchmark_summary.png"),
        "--windows",
        "365,180,90",
        "--alert-pips",
        "75",
        "--alert-winrate",
        "0.12",
        "--alert-sharpe",
        "0.22",
        "--alert-max-drawdown",
        "55",
        "--min-sharpe",
        "1.1",
        "--max-drawdown",
        "80",
        "--webhook",
        "https://example.com/hook",
    ]

    rc = rbp.main(args)
    assert rc == 0

    stdout = capsys.readouterr().out
    combined = json.loads(stdout)
    assert combined["benchmark_runs"]["latest_ts"] == benchmark_payload["latest_ts"]
    assert combined["summary"]["warnings"] == summary_payload["warnings"]

    # Ensure ordering and parameter propagation
    first_cmd, second_cmd = commands
    assert "run_benchmark_runs.py" in first_cmd[1]
    assert first_cmd[first_cmd.index("--windows") + 1] == "365,180,90"
    assert float(first_cmd[first_cmd.index("--alert-pips") + 1]) == pytest.approx(75.0)
    assert float(first_cmd[first_cmd.index("--alert-winrate") + 1]) == pytest.approx(0.12)
    assert float(first_cmd[first_cmd.index("--alert-sharpe") + 1]) == pytest.approx(0.22)
    assert float(first_cmd[first_cmd.index("--alert-max-drawdown") + 1]) == pytest.approx(55.0)
    assert first_cmd[first_cmd.index("--webhook") + 1] == "https://example.com/hook"
    assert "run_benchmark_summary.py" not in first_cmd[1]
    assert "report_benchmark_summary.py" in second_cmd[1]
    assert float(second_cmd[second_cmd.index("--min-sharpe") + 1]) == pytest.approx(1.1)
    assert float(second_cmd[second_cmd.index("--max-drawdown") + 1]) == pytest.approx(80.0)
    assert second_cmd[second_cmd.index("--webhook") + 1] == "https://example.com/hook"

    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    key = "USDJPY_conservative"
    assert snapshot["benchmarks"][key] == benchmark_payload["latest_ts"]
    pipeline_info = snapshot["benchmark_pipeline"][key]
    assert pipeline_info["warnings"] == summary_payload["warnings"]
    assert pipeline_info["summary_generated_at"] == summary_payload["generated_at"]
    pipeline_alert = pipeline_info["alert"]
    assert pipeline_alert["payload"]["deltas"]["delta_sharpe"] == pytest.approx(-0.4)
    assert pipeline_alert["payload"]["deltas"]["delta_max_drawdown"] == pytest.approx(-50.0)
    alert_payload = combined["benchmark_runs"]["alert"]["payload"]
    assert alert_payload["deltas"]["delta_sharpe"] == pytest.approx(-0.4)
    assert alert_payload["deltas"]["delta_max_drawdown"] == pytest.approx(-50.0)


def test_pipeline_errors_when_rolling_metrics_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys) -> None:
    baseline_path = tmp_path / "reports" / "baseline" / "USDJPY_conservative.json"
    _write_metrics(
        baseline_path,
        {
            "sharpe": 1.0,
            "max_drawdown": -60.0,
            "win_rate": 0.54,
            "aggregate_ev": AGGREGATE_SUCCESS,
        },
    )

    rolling_entries = []
    for window, payload in (
        (365, {"sharpe": 1.0, "win_rate": 0.55, "aggregate_ev": AGGREGATE_SUCCESS}),
        (
            180,
            {
                "sharpe": 1.1,
                "win_rate": 0.57,
                "max_drawdown": -30.0,
                "aggregate_ev": AGGREGATE_SUCCESS,
            },
        ),
        (
            90,
            {
                "sharpe": 1.2,
                "win_rate": 0.6,
                "max_drawdown": -20.0,
                "aggregate_ev": AGGREGATE_SUCCESS,
            },
        ),
    ):
        rolling_path = tmp_path / "reports" / "rolling" / str(window) / "USDJPY_conservative.json"
        _write_metrics(rolling_path, payload)
        rolling_entries.append({"window": window, "path": str(rolling_path)})

    benchmark_payload = {
        "baseline": str(baseline_path),
        "baseline_metrics": {},
        "rolling": rolling_entries,
        "latest_ts": "2024-06-10T00:00:00",
    }

    def fake_run(cmd: List[str], /) -> DummyCompletedProcess:
        if "run_benchmark_runs.py" in Path(cmd[1]).name:
            return DummyCompletedProcess(cmd, returncode=0, stdout=json.dumps(benchmark_payload))
        raise AssertionError("summary script should not be invoked when rolling metrics are invalid")

    monkeypatch.setattr(rbp, "_run_subprocess", fake_run)

    rc = rbp.main([
        "--bars",
        str(tmp_path / "bars.csv"),
        "--snapshot",
        str(tmp_path / "ops" / "runtime_snapshot.json"),
        "--summary-json",
        str(tmp_path / "reports" / "benchmark_summary.json"),
    ])

    assert rc == 1
    captured = capsys.readouterr()
    assert "missing max_drawdown" in captured.err
    assert captured.out == ""


def test_pipeline_errors_when_baseline_metrics_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys) -> None:
    baseline_path = tmp_path / "reports" / "baseline" / "USDJPY_conservative.json"
    _write_metrics(
        baseline_path,
        {
            "sharpe": 1.0,
            "max_drawdown": -65.0,
            "aggregate_ev": AGGREGATE_SUCCESS,
        },
    )

    rolling_entries = []
    for window in (365, 180, 90):
        path = tmp_path / "reports" / "rolling" / str(window) / "USDJPY_conservative.json"
        _write_metrics(
            path,
            {
                "win_rate": 0.6,
                "sharpe": 1.05,
                "max_drawdown": -45.0,
                "aggregate_ev": AGGREGATE_SUCCESS,
            },
        )
        rolling_entries.append({"window": window, "path": str(path)})

    benchmark_payload = {
        "baseline": str(baseline_path),
        "baseline_metrics": {},
        "rolling": rolling_entries,
        "latest_ts": "2024-06-10T00:00:00",
    }

    def fake_run(cmd: List[str], /) -> DummyCompletedProcess:
        if "run_benchmark_runs.py" in Path(cmd[1]).name:
            return DummyCompletedProcess(cmd, returncode=0, stdout=json.dumps(benchmark_payload))
        raise AssertionError("summary script should not be invoked when baseline metrics are invalid")

    monkeypatch.setattr(rbp, "_run_subprocess", fake_run)

    rc = rbp.main([
        "--bars",
        str(tmp_path / "bars.csv"),
        "--snapshot",
        str(tmp_path / "ops" / "runtime_snapshot.json"),
        "--summary-json",
        str(tmp_path / "reports" / "benchmark_summary.json"),
    ])

    assert rc == 1
    captured = capsys.readouterr()
    assert "baseline missing win_rate" in captured.err
    assert captured.out == ""


def test_pipeline_errors_when_aggregate_ev_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys) -> None:
    baseline_path = tmp_path / "reports" / "baseline" / "USDJPY_conservative.json"
    _write_metrics(
        baseline_path,
        {
            "sharpe": 0.9,
            "max_drawdown": -80.0,
            "win_rate": 0.52,
            "aggregate_ev": {"returncode": 1, "error": "boom"},
        },
    )

    rolling_entries = []
    for window in (365, 180, 90):
        path = tmp_path / "reports" / "rolling" / str(window) / "USDJPY_conservative.json"
        _write_metrics(
            path,
            {
                "win_rate": 0.6,
                "sharpe": 1.1,
                "max_drawdown": -40.0,
                "aggregate_ev": AGGREGATE_SUCCESS,
            },
        )
        rolling_entries.append({"window": window, "path": str(path)})

    benchmark_payload = {
        "baseline": str(baseline_path),
        "baseline_metrics": {},
        "rolling": rolling_entries,
        "latest_ts": "2024-06-10T00:00:00",
    }

    def fake_run(cmd: List[str], /) -> DummyCompletedProcess:
        if "run_benchmark_runs.py" in Path(cmd[1]).name:
            return DummyCompletedProcess(cmd, returncode=0, stdout=json.dumps(benchmark_payload))
        raise AssertionError("summary script should not be invoked when aggregate_ev fails")

    monkeypatch.setattr(rbp, "_run_subprocess", fake_run)

    rc = rbp.main([
        "--bars",
        str(tmp_path / "bars.csv"),
        "--snapshot",
        str(tmp_path / "ops" / "runtime_snapshot.json"),
        "--summary-json",
        str(tmp_path / "reports" / "benchmark_summary.json"),
    ])

    assert rc == 1
    captured = capsys.readouterr()
    assert "baseline aggregate_ev failed" in captured.err
    assert captured.out == ""


def test_pipeline_handles_benchmark_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys) -> None:
    def fake_run(cmd: List[str], /) -> DummyCompletedProcess:
        return DummyCompletedProcess(cmd, returncode=5, stdout="", stderr="boom")

    monkeypatch.setattr(rbp, "_run_subprocess", fake_run)

    rc = rbp.main([
        "--bars",
        str(tmp_path / "bars.csv"),
        "--snapshot",
        str(tmp_path / "ops" / "runtime_snapshot.json"),
    ])

    assert rc == 5
    out = capsys.readouterr().out
    assert out == ""


def test_pipeline_handles_summary_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys) -> None:
    baseline_path = tmp_path / "reports" / "baseline" / "USDJPY_conservative.json"
    _write_metrics(
        baseline_path,
        {
            "sharpe": 1.0,
            "max_drawdown": -70.0,
            "win_rate": 0.6,
            "aggregate_ev": AGGREGATE_SUCCESS,
        },
    )

    rolling_entries = []
    for window in (365, 180, 90):
        path = tmp_path / "reports" / "rolling" / str(window) / "USDJPY_conservative.json"
        _write_metrics(
            path,
            {
                "win_rate": 0.58,
                "sharpe": 1.0,
                "max_drawdown": -50.0,
                "aggregate_ev": AGGREGATE_SUCCESS,
            },
        )
        rolling_entries.append({"window": window, "path": str(path)})

    results: Iterator[DummyCompletedProcess] = iter([
        DummyCompletedProcess(
            [],
            returncode=0,
            stdout=json.dumps(
                {
                    "baseline": str(baseline_path),
                    "latest_ts": "2024-06-10T00:00:00",
                    "rolling": rolling_entries,
                }
            ),
        ),
        DummyCompletedProcess([], returncode=3, stdout="", stderr="bad"),
    ])

    def fake_run(cmd: List[str], /) -> DummyCompletedProcess:
        try:
            result = next(results)
        except StopIteration:  # pragma: no cover
            raise AssertionError("unexpected subprocess call")
        result.args = cmd
        return result

    monkeypatch.setattr(rbp, "_run_subprocess", fake_run)

    snapshot_path = tmp_path / "ops" / "runtime_snapshot.json"
    rc = rbp.main([
        "--bars",
        str(tmp_path / "bars.csv"),
        "--snapshot",
        str(snapshot_path),
    ])

    assert rc == 3
    assert not snapshot_path.exists()
    out = capsys.readouterr().out
    assert out == ""


def test_pipeline_errors_when_summary_missing_win_rate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    baseline_path = tmp_path / "reports" / "baseline" / "USDJPY_conservative.json"
    _write_metrics(
        baseline_path,
        {
            "sharpe": 1.1,
            "max_drawdown": -65.0,
            "win_rate": 0.61,
            "aggregate_ev": AGGREGATE_SUCCESS,
        },
    )

    rolling_entries = []
    for window in (365, 180, 90):
        path = tmp_path / "reports" / "rolling" / str(window) / "USDJPY_conservative.json"
        _write_metrics(
            path,
            {
                "sharpe": 1.0 + window / 1000.0,
                "max_drawdown": -40.0,
                "win_rate": 0.55,
                "aggregate_ev": AGGREGATE_SUCCESS,
            },
        )
        rolling_entries.append({"window": window, "path": str(path)})

    benchmark_payload = {
        "baseline": str(baseline_path),
        "rolling": rolling_entries,
        "latest_ts": "2024-06-10T00:00:00",
    }

    summary_payload = {
        "generated_at": "2024-06-10T01:00:00Z",
        "symbol": "USDJPY",
        "mode": "conservative",
        "baseline": {
            "trades": 120,
            "wins": 73,
            "total_pips": 210.0,
            "sharpe": 1.1,
            "max_drawdown": -65.0,
        },
        "rolling": [
            {
                "window": 365,
                "win_rate": 0.58,
                "sharpe": 1.3,
                "max_drawdown": -45.0,
            }
        ],
    }

    results: Iterator[DummyCompletedProcess] = iter(
        [
            DummyCompletedProcess([], returncode=0, stdout=json.dumps(benchmark_payload)),
            DummyCompletedProcess([], returncode=0, stdout=json.dumps(summary_payload)),
        ]
    )

    def fake_run(cmd: List[str], /) -> DummyCompletedProcess:
        try:
            result = next(results)
        except StopIteration:  # pragma: no cover
            raise AssertionError("unexpected subprocess call")
        result.args = cmd
        return result

    monkeypatch.setattr(rbp, "_run_subprocess", fake_run)

    rc = rbp.main([
        "--bars",
        str(tmp_path / "bars.csv"),
        "--snapshot",
        str(tmp_path / "ops" / "runtime_snapshot.json"),
    ])

    assert rc == 1
    captured = capsys.readouterr()
    assert "summary baseline missing win_rate" in captured.err
    assert captured.out == ""
