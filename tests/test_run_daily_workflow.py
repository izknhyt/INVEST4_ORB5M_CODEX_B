import json
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

import pytest
from core.utils import yaml_compat

from scripts import dukascopy_fetch, fetch_prices_api, run_daily_workflow, yfinance_fetch


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
    (repo_root / "data").mkdir(parents=True, exist_ok=True)

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

    fallback_csv = repo_root / "data/usdjpy_5m_2018-2024_utc.csv"
    fallback_csv.write_text(
        "timestamp,symbol,tf,o,h,l,c,v,spread\n"
        "2025-10-01T04:00:00,USDJPY,5m,147.96,147.98,147.94,147.97,140,0\n",
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

    meta = snapshot["ingest_meta"]["USDJPY_5m"]
    assert meta["primary_source"] == "api"
    assert meta["source_chain"] == [{"source": "api"}]
    assert meta["rows_validated"] == 2
    assert meta["freshness_minutes"] == pytest.approx(0.0)
    assert meta["synthetic_extension"] is False
    assert "fallbacks" not in meta
    assert meta["last_ingest_at"] == fixed_now.replace(tzinfo=timezone.utc).isoformat()
    assert meta["snapshot_path"] == str(snapshot_path)


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

    meta = snapshot["ingest_meta"]["USDJPY_5m"]
    assert meta["primary_source"] == "yfinance"
    assert [entry["source"] for entry in meta["source_chain"]] == ["yfinance"]
    assert meta["rows_validated"] == 2
    assert meta["freshness_minutes"] == pytest.approx(15.0)
    assert meta["synthetic_extension"] is False
    assert "fallbacks" not in meta
    assert meta["last_ingest_at"] == fixed_now.replace(tzinfo=timezone.utc).isoformat()


def test_yfinance_ingest_accepts_suffix_symbol(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    (repo_root / "ops/logs").mkdir(parents=True)
    (repo_root / "raw").mkdir()
    (repo_root / "validated/USDJPY").mkdir(parents=True)
    (repo_root / "features/USDJPY").mkdir(parents=True)
    (repo_root / "data").mkdir(parents=True, exist_ok=True)

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

    fallback_csv = repo_root / "data/usdjpy_5m_2018-2024_utc.csv"
    fallback_csv.write_text(
        "timestamp,symbol,tf,o,h,l,c,v,spread\n"
        "2025-10-01T04:00:00,USDJPY,5m,147.96,147.98,147.94,147.97,140,0\n",
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

    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    meta = snapshot["ingest_meta"]["USDJPY_5m"]
    assert meta["primary_source"] == "yfinance"
    chain = meta["source_chain"]
    assert chain[0]["source"] == "local_csv"
    assert chain[0]["detail"] == fallback_csv.name
    assert chain[-1]["source"] == "synthetic_local"
    assert meta["synthetic_extension"] is True
    assert meta["rows_validated"] == 4
    assert meta["freshness_minutes"] == pytest.approx(5.0)
    assert meta["last_ingest_at"] == fixed_now.replace(tzinfo=timezone.utc).isoformat()
    assert any(note["stage"] == "yfinance" for note in meta["fallbacks"])


def test_dukascopy_failure_falls_back_to_yfinance(tmp_path, monkeypatch):
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
        "2025-10-01T03:55:00,USDJPY,5m,149.10,149.12,149.08,149.11,90,0\n",
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

        @classmethod
        def fromisoformat(cls, value):
            return datetime.fromisoformat(value)

    monkeypatch.setattr(run_daily_workflow, "datetime", _FixedDatetime)

    def failing_fetch(*_args, **_kwargs):
        raise RuntimeError("dukascopy outage")

    monkeypatch.setattr(dukascopy_fetch, "fetch_bars", failing_fetch)

    fallback_calls = {}

    def fake_fetch(symbol, tf, *, start, end):
        fallback_calls["symbol"] = symbol
        fallback_calls["tf"] = tf
        fallback_calls["start"] = start
        fallback_calls["end"] = end
        return iter(
            [
                {
                    "timestamp": "2025-10-01T04:00:00",
                    "symbol": symbol,
                    "tf": tf,
                    "o": 149.30,
                    "h": 149.40,
                    "l": 149.20,
                    "c": 149.35,
                    "v": 105.0,
                    "spread": 0.0,
                },
                {
                    "timestamp": "2025-10-01T04:05:00",
                    "symbol": symbol,
                    "tf": tf,
                    "o": 149.35,
                    "h": 149.45,
                    "l": 149.30,
                    "c": 149.42,
                    "v": 110.0,
                    "spread": 0.0,
                },
            ]
        )

    monkeypatch.setattr(yfinance_fetch, "fetch_bars", fake_fetch)

    ingest_calls = []
    original_ingest = pull_prices.ingest_records

    def _tracking_ingest(records, **kwargs):
        rows = list(records)
        ingest_calls.append(
            {
                "rows": rows,
                "source_name": kwargs.get("source_name"),
            }
        )
        return original_ingest(rows, **kwargs)

    monkeypatch.setattr(pull_prices, "ingest_records", _tracking_ingest)

    exit_code = run_daily_workflow.main(
        [
            "--ingest",
            "--use-dukascopy",
            "--symbol",
            "USDJPY",
            "--mode",
            "conservative",
            "--dukascopy-freshness-threshold-minutes",
            "30",
            "--yfinance-lookback-minutes",
            "240",
        ]
    )

    assert exit_code == 0
    assert ingest_calls
    assert ingest_calls[0]["source_name"] == "yfinance"
    assert len(ingest_calls[0]["rows"]) == 2
    if len(ingest_calls) > 1:
        assert ingest_calls[-1]["source_name"] == "synthetic_local"
        assert len(ingest_calls[-1]["rows"]) == 2

    last_ts = datetime.fromisoformat("2025-10-01T03:55:00")
    expected_start = last_ts - timedelta(minutes=240)
    assert fallback_calls["start"] == expected_start
    assert fallback_calls["end"] == fixed_now

    csv_lines = validated_csv.read_text(encoding="utf-8").splitlines()
    assert csv_lines[-1].startswith("2025-10-01T04:05:00")

    features_csv = repo_root / "features/USDJPY/5m.csv"
    assert features_csv.exists()

    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert snapshot["ingest"]["USDJPY_5m"] == "2025-10-01T04:05:00"
    assert not anomaly_log_path.exists()

    meta = snapshot["ingest_meta"]["USDJPY_5m"]
    assert meta["primary_source"] == "dukascopy"
    chain_sources = [entry["source"] for entry in meta["source_chain"]]
    assert "yfinance" in chain_sources
    if meta["synthetic_extension"]:
        assert chain_sources[-1] == "synthetic_local"
    assert meta["rows_validated"] >= 2
    assert meta["freshness_minutes"] == pytest.approx(15.0)
    fallbacks = meta["fallbacks"]
    assert any(note["stage"] == "dukascopy" for note in fallbacks)
    dukascopy_note = next(note for note in fallbacks if note["stage"] == "dukascopy")
    assert "dukascopy outage" in dukascopy_note["reason"]
    assert meta["last_ingest_at"] == fixed_now.replace(tzinfo=timezone.utc).isoformat()
    assert meta["primary_parameters"]["offer_side"] == "bid"


def test_dukascopy_missing_dependency_falls_back_to_yfinance(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    (repo_root / "ops/logs").mkdir(parents=True)
    (repo_root / "raw").mkdir()
    (repo_root / "validated/USDJPY").mkdir(parents=True)
    (repo_root / "features/USDJPY").mkdir(parents=True)

    snapshot_path = repo_root / "ops/runtime_snapshot.json"
    snapshot_path.write_text(
        json.dumps({"ingest": {"USDJPY_5m": "2025-10-02T03:55:00"}}),
        encoding="utf-8",
    )

    validated_csv = repo_root / "validated/USDJPY/5m.csv"
    validated_csv.write_text(
        "timestamp,symbol,tf,o,h,l,c,v,spread\n"
        "2025-10-02T03:55:00,USDJPY,5m,147.94,147.95,147.93,147.94,100,0\n",
        encoding="utf-8",
    )

    from scripts import pull_prices

    anomaly_log_path = repo_root / "ops/logs/ingest_anomalies.jsonl"
    monkeypatch.setattr(pull_prices, "ANOMALY_LOG", anomaly_log_path)
    monkeypatch.setattr(run_daily_workflow, "ROOT", repo_root)

    fixed_now = datetime(2025, 10, 2, 4, 30)

    class _FixedDatetime(datetime):
        @classmethod
        def utcnow(cls):
            return fixed_now

    monkeypatch.setattr(run_daily_workflow, "datetime", _FixedDatetime)

    def _fail_load():
        raise RuntimeError("dukascopy_python is required")

    monkeypatch.setattr(run_daily_workflow, "_load_dukascopy_fetch", _fail_load)

    ticker_calls = {}

    def fake_resolve_ticker(symbol):
        ticker_calls["symbol"] = symbol
        return "JPY=X"

    monkeypatch.setattr(yfinance_fetch, "resolve_ticker", fake_resolve_ticker)

    fallback_calls = {}

    def fake_yf_fetch(symbol, tf, *, start, end):
        fallback_calls["symbol"] = symbol
        fallback_calls["tf"] = tf
        fallback_calls["start"] = start
        fallback_calls["end"] = end
        for idx, ts in enumerate(
            [
                "2025-10-02T04:00:00",
                "2025-10-02T04:05:00",
                "2025-10-02T04:10:00",
                "2025-10-02T04:15:00",
                "2025-10-02T04:20:00",
                "2025-10-02T04:25:00",
                "2025-10-02T04:30:00",
            ]
        ):
            yield {
                "timestamp": ts,
                "symbol": symbol,
                "tf": tf,
                "o": 147.98 + idx * 0.01,
                "h": 148.02 + idx * 0.01,
                "l": 147.96 + idx * 0.01,
                "c": 148.0 + idx * 0.01,
                "v": 150.0 + idx,
                "spread": 0.0,
            }

    monkeypatch.setattr(yfinance_fetch, "fetch_bars", fake_yf_fetch)

    exit_code = run_daily_workflow.main(
        [
            "--ingest",
            "--use-dukascopy",
            "--symbol",
            "USDJPY",
            "--mode",
            "conservative",
            "--yfinance-lookback-minutes",
            "90",
        ]
    )

    assert exit_code == 0
    assert ticker_calls["symbol"] == "USDJPY"
    assert fallback_calls["symbol"] == "USDJPY"
    assert fallback_calls["tf"] == "5m"
    last_ts = datetime.fromisoformat("2025-10-02T03:55:00")
    expected_start = last_ts - timedelta(minutes=90)
    assert fallback_calls["start"] == expected_start
    assert fallback_calls["end"] == fixed_now

    csv_lines = validated_csv.read_text(encoding="utf-8").splitlines()
    assert csv_lines[-1].startswith("2025-10-02T04:30:00")

    features_csv = repo_root / "features/USDJPY/5m.csv"
    assert features_csv.exists()

    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert snapshot["ingest"]["USDJPY_5m"] == "2025-10-02T04:30:00"
    meta = snapshot["ingest_meta"]["USDJPY_5m"]
    assert meta["primary_source"] == "dukascopy"
    chain_sources = [entry["source"] for entry in meta["source_chain"]]
    assert "yfinance" in chain_sources
    assert meta["freshness_minutes"] == pytest.approx(0.0)
    assert meta["rows_validated"] >= 7
    fallbacks = meta["fallbacks"]
    dukascopy_note = next(note for note in fallbacks if note["stage"] == "dukascopy")
    assert "dukascopy_python is required" in dukascopy_note["reason"]
    assert meta["last_ingest_at"] == fixed_now.replace(tzinfo=timezone.utc).isoformat()
    if anomaly_log_path.exists():
        assert anomaly_log_path.read_text(encoding="utf-8").strip() == ""
    assert meta["primary_parameters"]["offer_side"] == "bid"


def test_dukascopy_and_yfinance_missing_falls_back_to_local_csv(
    tmp_path, monkeypatch
):
    repo_root = tmp_path / "repo"
    (repo_root / "ops/logs").mkdir(parents=True)
    (repo_root / "raw").mkdir()
    (repo_root / "validated/USDJPY").mkdir(parents=True)
    (repo_root / "features/USDJPY").mkdir(parents=True)
    (repo_root / "data").mkdir(parents=True, exist_ok=True)

    snapshot_path = repo_root / "ops/runtime_snapshot.json"
    snapshot_path.write_text(
        json.dumps({"ingest": {"USDJPY_5m": "2025-10-03T03:55:00"}}),
        encoding="utf-8",
    )

    validated_csv = repo_root / "validated/USDJPY/5m.csv"
    validated_csv.write_text(
        "timestamp,symbol,tf,o,h,l,c,v,spread\n"
        "2025-10-03T03:55:00,USDJPY,5m,148.04,148.05,148.03,148.04,120,0\n",
        encoding="utf-8",
    )

    fallback_csv = repo_root / "data/usdjpy_5m_2018-2024_utc.csv"
    fallback_csv.write_text(
        "timestamp,symbol,tf,o,h,l,c,v,spread\n"
        "2025-10-03T04:00:00,USDJPY,5m,148.10,148.12,148.08,148.11,180,0\n"
        "2025-10-03T04:05:00,USDJPY,5m,148.12,148.14,148.10,148.13,175,0\n"
        "2025-10-03T04:10:00,USDJPY,5m,148.15,148.17,148.13,148.16,190,0\n"
        "2025-10-03T04:15:00,USDJPY,5m,148.18,148.20,148.16,148.19,185,0\n"
        "2025-10-03T04:20:00,USDJPY,5m,148.20,148.22,148.18,148.21,200,0\n",
        encoding="utf-8",
    )

    from scripts import pull_prices

    anomaly_log_path = repo_root / "ops/logs/ingest_anomalies.jsonl"
    monkeypatch.setattr(pull_prices, "ANOMALY_LOG", anomaly_log_path)
    monkeypatch.setattr(run_daily_workflow, "ROOT", repo_root)

    fixed_now = datetime(2025, 10, 3, 4, 30)

    class _FixedDatetime(datetime):
        @classmethod
        def utcnow(cls):
            return fixed_now

    monkeypatch.setattr(run_daily_workflow, "datetime", _FixedDatetime)

    def _fail_load():
        raise RuntimeError("dukascopy_python is required")

    monkeypatch.setattr(run_daily_workflow, "_load_dukascopy_fetch", _fail_load)

    def _missing_yfinance(*_args, **_kwargs):
        raise RuntimeError("missing yfinance dependency")

    monkeypatch.setattr(yfinance_fetch, "fetch_bars", _missing_yfinance)

    ingest_calls = []
    original_ingest = pull_prices.ingest_records

    def _tracking_ingest(records, **kwargs):
        rows = list(records)
        ingest_calls.append(
            {
                "rows": rows,
                "source_name": kwargs.get("source_name"),
            }
        )
        return original_ingest(rows, **kwargs)

    monkeypatch.setattr(pull_prices, "ingest_records", _tracking_ingest)

    exit_code = run_daily_workflow.main(
        [
            "--ingest",
            "--use-dukascopy",
            "--symbol",
            "USDJPY",
            "--mode",
            "conservative",
            "--yfinance-lookback-minutes",
            "120",
        ]
    )

    assert exit_code == 0
    assert ingest_calls
    assert ingest_calls[0]["source_name"].startswith("local_csv:")
    assert len(ingest_calls[0]["rows"]) == 5
    assert ingest_calls[-1]["source_name"] == "synthetic_local"
    assert len(ingest_calls[-1]["rows"]) == 1

    csv_lines = validated_csv.read_text(encoding="utf-8").splitlines()
    assert csv_lines[-1].startswith("2025-10-03T04:25:00")

    features_csv = repo_root / "features/USDJPY/5m.csv"
    assert features_csv.exists()

    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert snapshot["ingest"]["USDJPY_5m"] == "2025-10-03T04:25:00"
    if anomaly_log_path.exists():
        assert anomaly_log_path.read_text(encoding="utf-8").strip() == ""

    meta = snapshot["ingest_meta"]["USDJPY_5m"]
    assert meta["primary_source"] == "dukascopy"
    chain = meta["source_chain"]
    assert chain[0]["source"] == "local_csv"
    assert chain[0]["detail"] == fallback_csv.name
    assert chain[-1]["source"] == "synthetic_local"
    assert meta["synthetic_extension"] is True
    assert meta["rows_validated"] >= 6
    assert meta["freshness_minutes"] == pytest.approx(5.0)
    fallbacks = meta["fallbacks"]
    assert any(note["stage"] == "dukascopy" for note in fallbacks)
    assert any(note["stage"] == "yfinance" for note in fallbacks)
    assert meta["last_ingest_at"] == fixed_now.replace(tzinfo=timezone.utc).isoformat()
    assert meta["primary_parameters"]["offer_side"] == "bid"


def test_dukascopy_offer_side_metadata(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    (repo_root / "ops/logs").mkdir(parents=True)
    (repo_root / "raw").mkdir()
    (repo_root / "validated/USDJPY").mkdir(parents=True)
    (repo_root / "features/USDJPY").mkdir(parents=True)

    snapshot_path = repo_root / "ops/runtime_snapshot.json"
    snapshot_path.write_text(
        json.dumps({"ingest": {"USDJPY_5m": "2025-10-01T04:00:00"}}),
        encoding="utf-8",
    )

    validated_csv = repo_root / "validated/USDJPY/5m.csv"
    validated_csv.write_text(
        "timestamp,symbol,tf,o,h,l,c,v,spread\n"
        "2025-10-01T04:00:00,USDJPY,5m,148.00,148.02,147.98,148.01,120,0\n",
        encoding="utf-8",
    )

    from scripts import pull_prices

    anomaly_log_path = repo_root / "ops/logs/ingest_anomalies.jsonl"
    monkeypatch.setattr(pull_prices, "ANOMALY_LOG", anomaly_log_path)
    monkeypatch.setattr(run_daily_workflow, "ROOT", repo_root)

    fixed_now = datetime(2025, 10, 1, 5, 0)

    class _FixedDatetime(datetime):
        @classmethod
        def utcnow(cls):
            return fixed_now

        @classmethod
        def fromisoformat(cls, value):
            return datetime.fromisoformat(value)

    monkeypatch.setattr(run_daily_workflow, "datetime", _FixedDatetime)

    capture = {}

    def fake_fetch(symbol, tf, *, start, end, offer_side):
        capture["symbol"] = symbol
        capture["tf"] = tf
        capture["start"] = start
        capture["end"] = end
        capture["offer_side"] = offer_side
        return [
            {
                "timestamp": "2025-10-01T04:05:00",
                "symbol": symbol,
                "tf": tf,
                "o": 148.02,
                "h": 148.06,
                "l": 147.99,
                "c": 148.04,
                "v": 130.0,
                "spread": 0.0,
            },
            {
                "timestamp": "2025-10-01T04:55:00",
                "symbol": symbol,
                "tf": tf,
                "o": 148.05,
                "h": 148.09,
                "l": 148.01,
                "c": 148.07,
                "v": 135.0,
                "spread": 0.0,
            },
        ]

    monkeypatch.setattr(dukascopy_fetch, "fetch_bars", fake_fetch)

    exit_code = run_daily_workflow.main(
        [
            "--ingest",
            "--use-dukascopy",
            "--symbol",
            "USDJPY",
            "--mode",
            "conservative",
            "--dukascopy-lookback-minutes",
            "120",
            "--dukascopy-offer-side",
            "ask",
        ]
    )

    assert exit_code == 0
    assert capture["offer_side"] == "ask"
    assert capture["symbol"] == "USDJPY"
    assert capture["tf"] == "5m"
    assert capture["end"] == fixed_now

    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    meta = snapshot["ingest_meta"]["USDJPY_5m"]
    assert meta["primary_source"] == "dukascopy"
    assert meta["primary_parameters"]["offer_side"] == "ask"
    assert meta["freshness_minutes"] == pytest.approx(5.0)
    chain_sources = [entry["source"] for entry in meta["source_chain"]]
    assert chain_sources[0] == "dukascopy"
    assert not meta.get("fallbacks")


def test_local_csv_fallback_accepts_custom_backup(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    (repo_root / "ops/logs").mkdir(parents=True)
    (repo_root / "raw").mkdir()
    (repo_root / "validated/USDJPY").mkdir(parents=True)
    (repo_root / "features/USDJPY").mkdir(parents=True)
    (repo_root / "data").mkdir(parents=True, exist_ok=True)

    snapshot_path = repo_root / "ops/runtime_snapshot.json"
    snapshot_path.write_text(
        json.dumps({"ingest": {"USDJPY_5m": "2025-10-03T03:55:00"}}),
        encoding="utf-8",
    )

    validated_csv = repo_root / "validated/USDJPY/5m.csv"
    validated_csv.write_text(
        "timestamp,symbol,tf,o,h,l,c,v,spread\n"
        "2025-10-03T03:55:00,USDJPY,5m,148.04,148.05,148.03,148.04,120,0\n",
        encoding="utf-8",
    )

    custom_csv = repo_root / "data/custom_backup.csv"
    custom_csv.write_text(
        "timestamp,symbol,tf,o,h,l,c,v,spread\n"
        "2025-10-03T04:00:00,USDJPY,5m,149.00,149.02,148.98,149.01,160,0\n"
        "2025-10-03T04:05:00,USDJPY,5m,149.02,149.05,148.99,149.04,162,0\n",
        encoding="utf-8",
    )

    from scripts import pull_prices

    anomaly_log_path = repo_root / "ops/logs/ingest_anomalies.jsonl"
    monkeypatch.setattr(pull_prices, "ANOMALY_LOG", anomaly_log_path)
    monkeypatch.setattr(run_daily_workflow, "ROOT", repo_root)

    fixed_now = datetime(2025, 10, 3, 4, 10)

    class _FixedDatetime(datetime):
        @classmethod
        def utcnow(cls):
            return fixed_now

    monkeypatch.setattr(run_daily_workflow, "datetime", _FixedDatetime)

    def _fail_load():
        raise RuntimeError("dukascopy_python is required")

    monkeypatch.setattr(run_daily_workflow, "_load_dukascopy_fetch", _fail_load)

    def _missing_yfinance(*_args, **_kwargs):
        raise RuntimeError("missing yfinance dependency")

    monkeypatch.setattr(yfinance_fetch, "fetch_bars", _missing_yfinance)

    ingest_calls = []
    original_ingest = pull_prices.ingest_records

    def _tracking_ingest(records, **kwargs):
        rows = list(records)
        ingest_calls.append(
            {
                "rows": rows,
                "source_name": kwargs.get("source_name"),
            }
        )
        return original_ingest(rows, **kwargs)

    monkeypatch.setattr(pull_prices, "ingest_records", _tracking_ingest)

    exit_code = run_daily_workflow.main(
        [
            "--ingest",
            "--use-dukascopy",
            "--symbol",
            "USDJPY",
            "--mode",
            "conservative",
            "--local-backup-csv",
            "data/custom_backup.csv",
        ]
    )

    assert exit_code == 0
    assert ingest_calls
    assert ingest_calls[0]["source_name"] == "local_csv:custom_backup.csv"

    csv_lines = validated_csv.read_text(encoding="utf-8").splitlines()
    assert csv_lines[-1].startswith("2025-10-03T04:05:00")

    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    chain = snapshot["ingest_meta"]["USDJPY_5m"]["source_chain"]
    assert chain[0]["source"] == "local_csv"
    assert chain[0]["detail"] == "custom_backup.csv"

    fallbacks = snapshot["ingest_meta"]["USDJPY_5m"]["fallbacks"]
    assert any(note["stage"] == "dukascopy" for note in fallbacks)
    assert any(note["stage"] == "yfinance" for note in fallbacks)

