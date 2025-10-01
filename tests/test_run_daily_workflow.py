import json
import sys
from pathlib import Path
from datetime import datetime

import pytest
from core.utils import yaml_compat

from scripts import fetch_prices_api, run_daily_workflow, yfinance_fetch


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
        "--min-win-rate", "0.62",
        "--max-drawdown", "250.5",
        "--benchmark-windows", "400,200",
    ])

    assert exit_code == 0
    assert captured, "run_cmd should be invoked"
    cmd = captured[0]
    assert cmd[0] == sys.executable
    assert "--min-sharpe" in cmd
    assert cmd[cmd.index("--min-sharpe") + 1] == "1.5"
    assert "--min-win-rate" in cmd
    assert cmd[cmd.index("--min-win-rate") + 1] == "0.62"
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
    assert "--min-win-rate" not in cmd
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
        "--alert-sharpe", "0.3",
        "--alert-max-drawdown", "65",
        "--min-sharpe", "1.0",
        "--min-win-rate", "0.58",
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
    assert float(cmd[cmd.index("--alert-sharpe") + 1]) == pytest.approx(0.3)
    assert float(cmd[cmd.index("--alert-max-drawdown") + 1]) == pytest.approx(65.0)
    assert float(cmd[cmd.index("--min-sharpe") + 1]) == pytest.approx(1.0)
    assert float(cmd[cmd.index("--min-win-rate") + 1]) == pytest.approx(0.58)
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


def test_api_ingest_updates_snapshot(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    (repo_root / "ops/logs").mkdir(parents=True)
    (repo_root / "configs").mkdir()
    (repo_root / "raw").mkdir()
    (repo_root / "validated/USDJPY").mkdir(parents=True)
    (repo_root / "features/USDJPY").mkdir(parents=True)

    snapshot_path = repo_root / "ops/runtime_snapshot.json"
    snapshot_path.write_text(
        json.dumps({"ingest": {"USDJPY_5m": "2025-01-01T00:20:00"}}),
        encoding="utf-8",
    )

    validated_csv = repo_root / "validated/USDJPY/5m.csv"
    validated_csv.write_text(
        "timestamp,symbol,tf,o,h,l,c,v,spread\n"
        "2025-01-01T00:20:00,USDJPY,5m,150.0,150.1,149.9,150.05,120,0\n",
        encoding="utf-8",
    )

    config_path = repo_root / "configs/api_ingest.yml"
    credentials_path = repo_root / "configs/api_keys.yml"
    config = {
        "default_provider": "mock",
        "lookback_minutes": 45,
        "providers": {
            "mock": {
                "base_url": "http://example.test",
                "method": "GET",
                "query": {},
                "credentials": ["api_key"],
                "lookback_minutes": 15,
            }
        },
    }
    config_path.write_text(yaml_compat.safe_dump(config), encoding="utf-8")
    credentials_path.write_text(
        yaml_compat.safe_dump({"mock": {"api_key": "token"}}),
        encoding="utf-8",
    )

    from scripts import pull_prices

    anomaly_log_path = repo_root / "ops/logs/ingest_anomalies.jsonl"
    monkeypatch.setattr(pull_prices, "ANOMALY_LOG", anomaly_log_path)
    monkeypatch.setattr(run_daily_workflow, "ROOT", repo_root)

    fixed_now = datetime(2025, 1, 1, 0, 30)

    class _FixedDatetime(datetime):
        @classmethod
        def utcnow(cls):
            return fixed_now

    monkeypatch.setattr(run_daily_workflow, "datetime", _FixedDatetime)

    fetch_calls = {}

    def fake_fetch_prices(
        symbol,
        tf,
        *,
        start,
        end,
        provider=None,
        config_path=None,
        credentials_path=None,
        anomaly_log_path=None,
    ):
        fetch_calls["symbol"] = symbol
        fetch_calls["tf"] = tf
        fetch_calls["start"] = start
        fetch_calls["end"] = end
        fetch_calls["provider"] = provider
        fetch_calls["config_path"] = Path(config_path)
        fetch_calls["credentials_path"] = Path(credentials_path)
        fetch_calls["anomaly_log_path"] = anomaly_log_path
        return [
            {
                "timestamp": "2025-01-01T00:25:00Z",
                "symbol": symbol,
                "tf": tf,
                "o": 150.1,
                "h": 150.2,
                "l": 149.95,
                "c": 150.15,
                "v": 110.0,
                "spread": 0.1,
            },
            {
                "timestamp": "2025-01-01T00:30:00Z",
                "symbol": symbol,
                "tf": tf,
                "o": 150.15,
                "h": 150.3,
                "l": 150.05,
                "c": 150.25,
                "v": 108.0,
                "spread": 0.1,
            },
        ]

    monkeypatch.setattr(fetch_prices_api, "fetch_prices", fake_fetch_prices)

    exit_code = run_daily_workflow.main(
        [
            "--ingest",
            "--use-api",
            "--symbol",
            "USDJPY",
            "--mode",
            "conservative",
            "--api-provider",
            "mock",
            "--api-config",
            str(config_path),
            "--api-credentials",
            str(credentials_path),
        ]
    )

    assert exit_code == 0
    assert fetch_calls["symbol"] == "USDJPY"
    assert fetch_calls["tf"] == "5m"
    assert fetch_calls["provider"] == "mock"
    assert fetch_calls["start"] == datetime(2025, 1, 1, 0, 5)
    assert fetch_calls["end"] == fixed_now
    assert fetch_calls["config_path"] == config_path
    assert fetch_calls["credentials_path"] == credentials_path
    assert fetch_calls["anomaly_log_path"] is None

    csv_lines = validated_csv.read_text(encoding="utf-8").splitlines()
    assert len(csv_lines) == 4
    assert csv_lines[-1].startswith("2025-01-01T00:30:00")

    features_csv = repo_root / "features/USDJPY/5m.csv"
    assert features_csv.exists()

    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert snapshot["ingest"]["USDJPY_5m"] == "2025-01-01T00:30:00"
    assert not anomaly_log_path.exists()


def test_yfinance_ingest_updates_snapshot(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    (repo_root / "ops/logs").mkdir(parents=True)
    (repo_root / "raw").mkdir()
    (repo_root / "validated/USDJPY").mkdir(parents=True)
    (repo_root / "features/USDJPY").mkdir(parents=True)

    snapshot_path = repo_root / "ops/runtime_snapshot.json"
    snapshot_path.write_text(
        json.dumps({"ingest": {"USDJPY_5m": "2025-10-01T03:55:00"}}),
        encoding="utf-8",
    )

    validated_csv = repo_root / "validated/USDJPY/5m.csv"
    validated_csv.write_text(
        "timestamp,symbol,tf,o,h,l,c,v,spread\n"
        "2025-10-01T03:55:00,USDJPY,5m,147.94,147.95,147.93,147.94,100,0\n",
        encoding="utf-8",
    )

    from scripts import pull_prices

    anomaly_log_path = repo_root / "ops/logs/ingest_anomalies.jsonl"
    monkeypatch.setattr(pull_prices, "ANOMALY_LOG", anomaly_log_path)
    monkeypatch.setattr(run_daily_workflow, "ROOT", repo_root)

    fixed_now = datetime(2025, 10, 1, 4, 20)

    class _FixedDatetime(datetime):
        @classmethod
        def utcnow(cls):
            return fixed_now

    monkeypatch.setattr(run_daily_workflow, "datetime", _FixedDatetime)

    def fake_fetch_bars(symbol, tf, *, start, end):
        assert symbol == "USDJPY"
        assert tf == "5m"
        assert start == datetime(2025, 10, 1, 3, 20)
        assert end == fixed_now
        yield {
            "timestamp": "2025-10-01T04:00:00",
            "symbol": symbol,
            "tf": tf,
            "o": 147.95,
            "h": 147.99,
            "l": 147.92,
            "c": 147.97,
            "v": 150.0,
            "spread": 0.0,
        }
        yield {
            "timestamp": "2025-10-01T04:05:00",
            "symbol": symbol,
            "tf": tf,
            "o": 147.97,
            "h": 148.01,
            "l": 147.94,
            "c": 147.99,
            "v": 160.0,
            "spread": 0.0,
        }

    monkeypatch.setattr(yfinance_fetch, "fetch_bars", fake_fetch_bars)

    exit_code = run_daily_workflow.main(
        [
            "--ingest",
            "--use-yfinance",
            "--symbol",
            "USDJPY",
            "--mode",
            "conservative",
            "--yfinance-lookback-minutes",
            "35",
        ]
    )

    assert exit_code == 0

    csv_lines = validated_csv.read_text(encoding="utf-8").splitlines()
    assert csv_lines[-1].startswith("2025-10-01T04:05:00")

    features_csv = repo_root / "features/USDJPY/5m.csv"
    assert features_csv.exists()

    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert snapshot["ingest"]["USDJPY_5m"] == "2025-10-01T04:05:00"


def test_yfinance_ingest_accepts_suffix_symbol(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    (repo_root / "ops/logs").mkdir(parents=True)
    (repo_root / "raw").mkdir()
    (repo_root / "validated/USDJPY").mkdir(parents=True)
    (repo_root / "features/USDJPY").mkdir(parents=True)

    snapshot_path = repo_root / "ops/runtime_snapshot.json"
    snapshot_path.write_text(
        json.dumps({"ingest": {"USDJPY_5m": "2025-10-01T03:55:00"}}),
        encoding="utf-8",
    )

    validated_csv = repo_root / "validated/USDJPY/5m.csv"
    validated_csv.write_text(
        "timestamp,symbol,tf,o,h,l,c,v,spread\n"
        "2025-10-01T03:55:00,USDJPY,5m,147.94,147.95,147.93,147.94,100,0\n",
        encoding="utf-8",
    )

    from scripts import pull_prices

    anomaly_log_path = repo_root / "ops/logs/ingest_anomalies.jsonl"
    monkeypatch.setattr(pull_prices, "ANOMALY_LOG", anomaly_log_path)
    monkeypatch.setattr(run_daily_workflow, "ROOT", repo_root)

    fixed_now = datetime(2025, 10, 1, 4, 20)

    class _FixedDatetime(datetime):
        @classmethod
        def utcnow(cls):
            return fixed_now

    monkeypatch.setattr(run_daily_workflow, "datetime", _FixedDatetime)

    captured = {}

    def fake_fetch_bars(symbol, tf, *, start, end):
        captured["symbol"] = symbol
        captured["tf"] = tf
        captured["start"] = start
        captured["end"] = end
        return []

    monkeypatch.setattr(yfinance_fetch, "fetch_bars", fake_fetch_bars)

    exit_code = run_daily_workflow.main(
        [
            "--ingest",
            "--use-yfinance",
            "--symbol",
            "USDJPY=X",
            "--mode",
            "conservative",
            "--yfinance-lookback-minutes",
            "35",
        ]
    )

    assert exit_code == 0
    assert captured["symbol"] == "USDJPY"
