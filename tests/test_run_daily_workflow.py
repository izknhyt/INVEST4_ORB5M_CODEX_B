import json
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Dict
import textwrap

import pytest
from core.utils import yaml_compat

from scripts import (
    dukascopy_fetch,
    fetch_prices_api,
    ingest_providers,
    run_daily_workflow,
    yfinance_fetch,
)


def _capture_run_cmd(monkeypatch):
    captured = []

    def fake_run_cmd(cmd):
        captured.append(cmd)
        return 0

    monkeypatch.setattr(run_daily_workflow, "run_cmd", fake_run_cmd)
    return captured


def test_run_cmd_executes_with_repo_root(monkeypatch):
    called = {}

    def fake_run(cmd, *, check, cwd):
        called["cmd"] = cmd
        called["check"] = check
        called["cwd"] = cwd
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(run_daily_workflow.subprocess, "run", fake_run)

    exit_code = run_daily_workflow.run_cmd(["echo", "hello"])

    assert exit_code == 0
    assert called["cmd"] == ["echo", "hello"]
    assert called["check"] is False
    assert called["cwd"] == run_daily_workflow.ROOT


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


def test_update_state_resolves_bars_override(monkeypatch):
    captured = _capture_run_cmd(monkeypatch)

    exit_code = run_daily_workflow.main([
        "--update-state",
        "--bars",
        "validated/override.csv",
    ])

    assert exit_code == 0
    assert captured, "run_cmd should be invoked"
    cmd = captured[0]
    bars_value = cmd[cmd.index("--bars") + 1]
    expected = (run_daily_workflow.ROOT / "validated/override.csv").resolve()
    assert Path(bars_value) == expected


def test_check_benchmark_freshness_passes_pipeline_and_override(monkeypatch):
    captured = _capture_run_cmd(monkeypatch)

    exit_code = run_daily_workflow.main([
        "--check-benchmark-freshness",
        "--benchmark-freshness-base-max-age-hours",
        "9.25",
        "--benchmark-freshness-max-age-hours",
        "8.5",
        "--benchmark-freshness-targets",
        "USDJPY:conservative",
    ])

    assert exit_code == 0
    assert captured, "run_cmd should be invoked"
    cmd = captured[0]
    assert "--max-age-hours" in cmd
    assert float(cmd[cmd.index("--max-age-hours") + 1]) == pytest.approx(9.25)
    assert "--benchmark-freshness-base-max-age-hours" not in cmd
    assert "--benchmark-freshness-max-age-hours" in cmd
    assert cmd[cmd.index("--benchmark-freshness-max-age-hours") + 1] == "8.5"


def test_check_benchmark_freshness_defaults_pipeline_threshold(monkeypatch):
    captured = _capture_run_cmd(monkeypatch)

    exit_code = run_daily_workflow.main([
        "--check-benchmark-freshness",
        "--benchmark-freshness-targets",
        "USDJPY:conservative",
    ])

    assert exit_code == 0
    assert captured, "run_cmd should be invoked"
    cmd = captured[0]
    assert "--benchmark-freshness-base-max-age-hours" not in cmd
    assert "--max-age-hours" in cmd
    assert float(cmd[cmd.index("--max-age-hours") + 1]) == pytest.approx(6.0)


def test_check_data_quality_command_defaults(monkeypatch):
    captured = _capture_run_cmd(monkeypatch)

    exit_code = run_daily_workflow.main(["--check-data-quality"])

    assert exit_code == 0
    assert captured, "run_cmd should be invoked"
    cmd = captured[0]
    assert "check_data_quality.py" in cmd[1]
    expected_csv = run_daily_workflow._resolve_default_bars_csv("USDJPY")
    _assert_path_arg(
        cmd,
        "--csv",
        expected_csv,
    )
    tf_token = Path(expected_csv).stem.lower()
    symbol_lower = "usdjpy"
    dq_dir = run_daily_workflow.ROOT / "reports/data_quality"
    _assert_path_arg(
        cmd,
        "--out-json",
        dq_dir / f"{symbol_lower}_{tf_token}_summary.json",
    )
    _assert_path_arg(
        cmd,
        "--out-gap-csv",
        dq_dir / f"{symbol_lower}_{tf_token}_gap_inventory.csv",
    )
    _assert_path_arg(
        cmd,
        "--out-gap-json",
        dq_dir / f"{symbol_lower}_{tf_token}_gap_inventory.json",
    )
    assert "--calendar-day-summary" in cmd
    assert "--fail-on-calendar-day-warnings" in cmd
    coverage_value = float(cmd[cmd.index("--fail-under-coverage") + 1])
    assert coverage_value == pytest.approx(0.995)
    calendar_threshold = float(
        cmd[cmd.index("--calendar-day-coverage-threshold") + 1]
    )
    assert calendar_threshold == pytest.approx(0.98)
    assert int(cmd[cmd.index("--calendar-day-max-report") + 1]) == 10
    assert "--fail-on-duplicate-groups" in cmd
    duplicate_threshold = int(
        cmd[cmd.index("--fail-on-duplicate-groups") + 1]
    )
    assert duplicate_threshold == 5
    assert "--fail-on-duplicate-occurrences" in cmd
    duplicate_occurrence_threshold = int(
        cmd[cmd.index("--fail-on-duplicate-occurrences") + 1]
    )
    assert duplicate_occurrence_threshold == 3


def test_check_data_quality_propagates_webhook(monkeypatch):
    captured = _capture_run_cmd(monkeypatch)

    exit_code = run_daily_workflow.main(
        [
            "--check-data-quality",
            "--webhook",
            "https://example.com/hook",
            "--data-quality-webhook-timeout",
            "9.5",
        ]
    )

    assert exit_code == 0
    cmd = captured[0]
    assert "--webhook" in cmd
    assert cmd[cmd.index("--webhook") + 1] == "https://example.com/hook"
    assert "--webhook-timeout" in cmd
    assert cmd[cmd.index("--webhook-timeout") + 1] == "9.5"


def test_check_data_quality_supports_overrides(monkeypatch, tmp_path):
    captured = _capture_run_cmd(monkeypatch)
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    monkeypatch.setattr(run_daily_workflow, "ROOT", repo_root)

    exit_code = run_daily_workflow.main(
        [
            "--check-data-quality",
            "--symbol",
            "eurusd",
            "--bars",
            "validated/custom.csv",
            "--data-quality-output-dir",
            "reports/custom",
            "--data-quality-summary-json",
            "reports/overrides/summary.json",
            "--data-quality-gap-csv",
            "reports/overrides/gaps.csv",
            "--data-quality-gap-json",
            "reports/overrides/gaps.json",
            "--data-quality-coverage-threshold",
            "0.97",
            "--data-quality-calendar-threshold",
            "0.93",
            "--data-quality-calendar-max-report",
            "5",
            "--data-quality-duplicate-groups-threshold",
            "7",
            "--data-quality-duplicate-occurrences-threshold",
            "4",
        ]
    )

    assert exit_code == 0
    cmd = captured[0]
    assert cmd[cmd.index("--symbol") + 1] == "EURUSD"
    _assert_path_arg(cmd, "--csv", repo_root / "validated/custom.csv")
    _assert_path_arg(
        cmd,
        "--out-json",
        repo_root / "reports/overrides/summary.json",
    )
    _assert_path_arg(
        cmd,
        "--out-gap-csv",
        repo_root / "reports/overrides/gaps.csv",
    )
    _assert_path_arg(
        cmd,
        "--out-gap-json",
        repo_root / "reports/overrides/gaps.json",
    )
    assert int(cmd[cmd.index("--calendar-day-max-report") + 1]) == 5
    assert float(cmd[cmd.index("--fail-under-coverage") + 1]) == pytest.approx(0.97)
    assert float(cmd[cmd.index("--calendar-day-coverage-threshold") + 1]) == pytest.approx(
        0.93
    )
    assert int(cmd[cmd.index("--fail-on-duplicate-groups") + 1]) == 7
    assert int(cmd[cmd.index("--fail-on-duplicate-occurrences") + 1]) == 4


def test_check_data_quality_disables_duplicate_guard(monkeypatch):
    captured = _capture_run_cmd(monkeypatch)

    exit_code = run_daily_workflow.main(
        [
            "--check-data-quality",
            "--data-quality-duplicate-groups-threshold",
            "0",
        ]
    )

    assert exit_code == 0
    cmd = captured[0]
    assert "--fail-on-duplicate-groups" not in cmd


def test_check_data_quality_disables_duplicate_occurrence_guard(monkeypatch):
    captured = _capture_run_cmd(monkeypatch)

    exit_code = run_daily_workflow.main(
        [
            "--check-data-quality",
            "--data-quality-duplicate-occurrences-threshold",
            "0",
        ]
    )

    assert exit_code == 0
    cmd = captured[0]
    assert "--fail-on-duplicate-occurrences" not in cmd


def test_default_bars_prefers_header(monkeypatch, tmp_path):
    repo_root = tmp_path / "repo"
    header_path = repo_root / "validated/USDJPY/5m_with_header.csv"
    legacy_path = repo_root / "validated/USDJPY/5m.csv"
    header_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.write_text("timestamp,symbol,tf,o,h,l,c,v,spread\n", encoding="utf-8")
    header_path.write_text("timestamp,symbol,tf,o,h,l,c,v,spread\n", encoding="utf-8")
    monkeypatch.setattr(run_daily_workflow, "ROOT", repo_root)

    default_path = run_daily_workflow._resolve_default_bars_csv("USDJPY")

    assert default_path == header_path


def test_default_bars_falls_back_when_header_missing(monkeypatch, tmp_path):
    repo_root = tmp_path / "repo"
    legacy_path = repo_root / "validated/USDJPY/5m.csv"
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.write_text("timestamp,symbol,tf,o,h,l,c,v,spread\n", encoding="utf-8")
    monkeypatch.setattr(run_daily_workflow, "ROOT", repo_root)

    default_path = run_daily_workflow._resolve_default_bars_csv("USDJPY")

    assert default_path == legacy_path


def test_check_data_quality_validates_thresholds():
    with pytest.raises(SystemExit):
        run_daily_workflow.main(
            ["--check-data-quality", "--data-quality-coverage-threshold", "1.5"]
        )
    with pytest.raises(SystemExit):
        run_daily_workflow.main(
            ["--check-data-quality", "--data-quality-calendar-threshold", "-0.1"]
        )
    with pytest.raises(SystemExit):
        run_daily_workflow.main(
            ["--check-data-quality", "--data-quality-calendar-max-report", "0"]
        )
    with pytest.raises(SystemExit):
        run_daily_workflow.main(
            ["--check-data-quality", "--data-quality-webhook-timeout", "0"]
        )
    with pytest.raises(SystemExit):
        run_daily_workflow.main(
            ["--check-data-quality", "--data-quality-duplicate-groups-threshold", "-1"]
        )
    with pytest.raises(SystemExit):
        run_daily_workflow.main(
            [
                "--check-data-quality",
                "--data-quality-duplicate-occurrences-threshold",
                "-2",
            ]
        )


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


def test_ingest_pull_prices_uses_symbol_specific_source(monkeypatch):
    captured = _capture_run_cmd(monkeypatch)

    exit_code = run_daily_workflow.main([
        "--ingest",
        "--symbol",
        "GBPJPY",
    ])

    assert exit_code == 0
    assert captured, "pull_prices command should be invoked"
    cmd = captured[0]
    assert "pull_prices.py" in cmd[1]
    source_value = cmd[cmd.index("--source") + 1]
    expected = (run_daily_workflow.ROOT / "data/gbpjpy_5m_2018-2024_utc.csv").resolve()
    assert Path(source_value) == expected


def test_ingest_pull_prices_respects_local_backup_override(monkeypatch):
    captured = _capture_run_cmd(monkeypatch)

    exit_code = run_daily_workflow.main(
        ["--ingest", "--local-backup-csv", "data/custom_backup.csv"]
    )

    assert exit_code == 0
    assert captured, "pull_prices command should be invoked"
    cmd = captured[0]
    source_value = cmd[cmd.index("--source") + 1]
    expected = (run_daily_workflow.ROOT / "data/custom_backup.csv").resolve()
    assert Path(source_value) == expected


def test_optimize_uses_absolute_paths(monkeypatch):
    captured = _capture_run_cmd(monkeypatch)

    exit_code = run_daily_workflow.main(["--optimize"])

    assert exit_code == 0
    assert captured, "run_cmd should be invoked"
    cmd = captured[0]
    root = run_daily_workflow.ROOT
    _assert_path_arg(cmd, "--csv", root / "data/usdjpy_5m_2018-2024_utc.csv")
    _assert_path_arg(cmd, "--report", root / "reports/auto_optimize.json")


def test_optimize_propagates_symbol_mode_and_csv(monkeypatch):
    captured = _capture_run_cmd(monkeypatch)

    exit_code = run_daily_workflow.main([
        "--optimize",
        "--symbol", "GBPJPY",
        "--mode", "bridge",
    ])

    assert exit_code == 0
    assert captured, "run_cmd should be invoked"
    cmd = captured[0]
    assert cmd[cmd.index("--symbol") + 1] == "GBPJPY"
    assert cmd[cmd.index("--mode") + 1] == "bridge"
    root = run_daily_workflow.ROOT
    _assert_path_arg(cmd, "--csv", root / "data/gbpjpy_5m_2018-2024_utc.csv")


def test_analyze_latency_uses_absolute_paths(monkeypatch):
    captured = _capture_run_cmd(monkeypatch)

    exit_code = run_daily_workflow.main(["--analyze-latency"])

    assert exit_code == 0
    assert captured, "run_cmd should be invoked"
    cmd = captured[0]
    root = run_daily_workflow.ROOT
    _assert_path_arg(cmd, "--input", root / "ops/signal_latency.csv")
    _assert_path_arg(cmd, "--rollup-output", root / "ops/signal_latency_rollup.csv")
    _assert_path_arg(cmd, "--heartbeat-file", root / "ops/latency_job_heartbeat.json")
    _assert_path_arg(cmd, "--archive-dir", root / "ops/signal_latency_archive")
    _assert_path_arg(cmd, "--archive-manifest", root / "ops/signal_latency_archive/manifest.jsonl")
    _assert_path_arg(cmd, "--json-out", root / "reports/signal_latency_summary.json")


def test_observability_chain_respects_config(monkeypatch, tmp_path):
    captured: list[list[str]] = []

    def fake_run_cmd(cmd):
        captured.append(cmd)
        return 0

    monkeypatch.setattr(run_daily_workflow, "run_cmd", fake_run_cmd)

    config_text = textwrap.dedent(
        """
        latency:
          argv:
            - --dry-run-alert
        weekly:
          argv:
            - --dry-run-webhook
            - --job-name
            - custom-weekly
        dashboard:
          argv:
            - --dataset
            - latency
            - --job-name
            - custom-dashboard
        """
    )
    config_path = tmp_path / "observability.yaml"
    config_path.write_text(config_text, encoding="utf-8")

    exit_code = run_daily_workflow.main(
        ["--observability", "--observability-config", str(config_path)]
    )

    assert exit_code == 0
    assert [Path(cmd[1]).name for cmd in captured] == [
        "analyze_signal_latency.py",
        "summarize_runs.py",
        "export_dashboard_data.py",
    ]
    assert "--dry-run-alert" in captured[0]
    assert "--dry-run-webhook" in captured[1]
    assert captured[1][captured[1].index("--job-name") + 1] == "custom-weekly"
    assert captured[2].count("--dataset") >= 1
    assert captured[2][captured[2].index("--job-name") + 1] == "custom-dashboard"


def test_observability_chain_stops_after_failure(monkeypatch, tmp_path):
    order: list[str] = []

    def fake_run_cmd(cmd):
        order.append(Path(cmd[1]).name)
        return 9 if len(order) == 1 else 0

    monkeypatch.setattr(run_daily_workflow, "run_cmd", fake_run_cmd)
    config_path = tmp_path / "observability.yaml"
    config_path.write_text("{}", encoding="utf-8")

    exit_code = run_daily_workflow.main(
        ["--observability", "--observability-config", str(config_path)]
    )

    assert exit_code == 9
    assert order == ["analyze_signal_latency.py"]


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


def test_api_ingest_updates_snapshot(tmp_path, monkeypatch, capsys):
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
    captured = capsys.readouterr().out
    assert "[wf] api_ingest" in captured
    assert "rows=2" in captured
    assert "last_ts=2025-01-01T00:30:00" in captured
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


def test_api_ingest_falls_back_to_local_csv(tmp_path, monkeypatch, capsys):
    repo_root = tmp_path / "repo"
    (repo_root / "ops/logs").mkdir(parents=True)
    (repo_root / "configs").mkdir()
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
        "2025-10-01T04:00:00,USDJPY,5m,147.95,147.99,147.92,147.97,140,0\n"
        "2025-10-01T04:05:00,USDJPY,5m,147.97,148.02,147.94,148.00,135,0\n",
        encoding="utf-8",
    )

    config_path = repo_root / "configs/api_ingest.yml"
    credentials_path = repo_root / "configs/api_keys.yml"
    config = {
        "default_provider": "mock",
        "lookback_minutes": 30,
        "providers": {
            "mock": {
                "base_url": "http://example.test",
                "method": "GET",
                "credentials": ["token"],
            }
        },
    }
    config_path.write_text(yaml_compat.safe_dump(config), encoding="utf-8")
    credentials_path.write_text(
        yaml_compat.safe_dump({"mock": {"token": "secret"}}),
        encoding="utf-8",
    )

    from scripts import pull_prices

    anomaly_log_path = repo_root / "ops/logs/ingest_anomalies.jsonl"
    monkeypatch.setattr(pull_prices, "ANOMALY_LOG", anomaly_log_path)
    monkeypatch.setattr(run_daily_workflow, "ROOT", repo_root)

    fixed_now = datetime(2025, 10, 1, 4, 15)

    class _FixedDatetime(datetime):
        @classmethod
        def utcnow(cls):
            return fixed_now

    monkeypatch.setattr(run_daily_workflow, "datetime", _FixedDatetime)

    def _failing_fetch(*_args, **_kwargs):
        raise RuntimeError("mock provider unavailable")

    monkeypatch.setattr(fetch_prices_api, "fetch_prices", _failing_fetch)

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
    fallback_logs = capsys.readouterr().out
    assert "[wf] local_csv_ingest" in fallback_logs
    assert "rows=" in fallback_logs
    assert "last_ts=" in fallback_logs

    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    meta = snapshot["ingest_meta"]["USDJPY_5m"]
    assert meta["primary_source"] == "api"
    chain = meta["source_chain"]
    assert chain[0]["source"] == "local_csv"
    assert chain[-1]["source"] == "synthetic_local"
    assert meta["synthetic_extension"] is True
    fallbacks = meta["fallbacks"]
    api_note = next(note for note in fallbacks if note["stage"] == "api")
    assert "mock provider unavailable" in api_note["reason"]
    local_note = next(note for note in fallbacks if note["stage"] == "local_csv")
    assert Path(local_note["detail"]) == fallback_csv
    assert local_note.get("next_source") == "synthetic_local"
    assert meta["local_backup_path"] == str(fallback_csv)
    assert snapshot["ingest"]["USDJPY_5m"] >= "2025-10-01T04:05:00"

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

    def fake_fetch_bars(symbol, tf, *, start, end, **kwargs):
        assert symbol == "USDJPY"
        assert tf == "5m"
        assert start == datetime(2025, 10, 1, 3, 20)
        assert end == fixed_now
        assert "offer_side" not in kwargs
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


@pytest.mark.parametrize(
    "last_ts_offset",
    [None, timedelta(days=10)],
    ids=["missing_last_ts", "stale_last_ts"],
)
def test_yfinance_ingest_clamps_lookback_like_helper(
    tmp_path, monkeypatch, capsys, last_ts_offset
):
    repo_root = tmp_path / "repo"
    (repo_root / "ops").mkdir(parents=True)
    (repo_root / "raw/USDJPY").mkdir(parents=True)
    (repo_root / "validated/USDJPY").mkdir(parents=True)
    (repo_root / "features/USDJPY").mkdir(parents=True)

    snapshot_path_obj = repo_root / "ops/runtime_snapshot.json"
    snapshot_path_obj.write_text("{}", encoding="utf-8")

    now = datetime(2025, 10, 8, 5, 0)
    monkeypatch.setattr(run_daily_workflow, "_utcnow_naive", lambda: now)
    monkeypatch.setattr(run_daily_workflow, "ROOT", repo_root)

    last_ts = None if last_ts_offset is None else now - last_ts_offset

    expected_start = ingest_providers.compute_yfinance_fallback_start(
        last_ts=last_ts,
        lookback_minutes=60,
        now=now,
    )

    captured: Dict[str, object] = {}

    def fake_fetch(fetch_bars, symbol, tf, *, start, end, empty_reason):
        captured["symbol"] = symbol
        captured["tf"] = tf
        captured["start"] = start
        captured["end"] = end
        captured["empty_reason"] = empty_reason
        return [
            {
                "timestamp": (now - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%S"),
                "symbol": symbol,
                "tf": tf,
                "o": 1.0,
                "h": 1.0,
                "l": 1.0,
                "c": 1.0,
                "v": 0.0,
                "spread": 0.0,
            }
        ]

    monkeypatch.setattr(run_daily_workflow, "_fetch_yfinance_records", fake_fetch)

    def fake_get_last_processed_ts(
        _symbol, _tf, *, snapshot_path, validated_path
    ):
        assert Path(snapshot_path) == snapshot_path_obj
        assert Path(validated_path) == repo_root / "validated/USDJPY/5m.csv"
        return last_ts

    def fake_ingest(
        records,
        *,
        symbol,
        tf,
        snapshot_path,
        raw_path,
        validated_path,
        features_path,
        source_name,
        **_kwargs,
    ):
        assert symbol == "USDJPY"
        assert tf == "5m"
        assert Path(snapshot_path) == snapshot_path_obj
        assert Path(raw_path) == repo_root / "raw/USDJPY/5m.csv"
        assert Path(validated_path) == repo_root / "validated/USDJPY/5m.csv"
        assert Path(features_path) == repo_root / "features/USDJPY/5m.csv"
        assert source_name == "yfinance"
        return {
            "rows_raw": len(records),
            "rows_validated": len(records),
            "rows_featured": 0,
            "last_ts_now": now.isoformat(timespec="seconds"),
            "source": source_name,
        }

    monkeypatch.setattr(run_daily_workflow, "_persist_ingest_metadata", lambda **_kwargs: None)

    ctx = run_daily_workflow.IngestContext(
        symbol="USDJPY",
        tf="5m",
        snapshot_path=snapshot_path_obj,
        raw_path=repo_root / "raw/USDJPY/5m.csv",
        validated_path=repo_root / "validated/USDJPY/5m.csv",
        features_path=repo_root / "features/USDJPY/5m.csv",
        ingest_records=fake_ingest,
        get_last_processed_ts=fake_get_last_processed_ts,
        fallback_notes=[],
        local_backup_path=None,
        synthetic_allowed=True,
    )

    args = SimpleNamespace(symbol="USDJPY", yfinance_lookback_minutes=60)

    result, exit_code = run_daily_workflow._run_yfinance_ingest(ctx, args)

    assert exit_code == 0
    assert captured["symbol"] == "USDJPY"
    assert captured["tf"] == "5m"
    assert captured["start"] == expected_start
    assert captured["end"] == now
    assert result["rows_validated"] == 1

    output = capsys.readouterr().out
    assert expected_start.isoformat(timespec="seconds") in output

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

    def fake_fetch_bars(symbol, tf, *, start, end, **kwargs):
        captured["symbol"] = symbol
        captured["tf"] = tf
        captured["start"] = start
        captured["end"] = end
        captured["extra"] = kwargs
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
    assert captured["extra"] == {}

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
    fallbacks = meta["fallbacks"]
    assert any(note["stage"] == "yfinance" for note in fallbacks)
    local_note = next(note for note in fallbacks if note["stage"] == "local_csv")
    assert Path(local_note["detail"]) == fallback_csv
    assert meta["local_backup_path"] == str(fallback_csv)


def test_yfinance_ingest_accepts_short_suffix_symbol(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    (repo_root / "ops/logs").mkdir(parents=True)
    (repo_root / "raw").mkdir()
    (repo_root / "validated/JPY=X").mkdir(parents=True)
    (repo_root / "features/JPY=X").mkdir(parents=True)

    snapshot_path = repo_root / "ops/runtime_snapshot.json"
    snapshot_path.write_text(
        json.dumps({"ingest": {"JPY=X_5m": "2025-10-01T03:55:00"}}),
        encoding="utf-8",
    )

    validated_csv = repo_root / "validated/JPY=X/5m.csv"
    validated_csv.write_text(
        "timestamp,symbol,tf,o,h,l,c,v,spread\n"
        "2025-10-01T03:55:00,JPY=X,5m,149.10,149.12,149.08,149.11,90,0\n",
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

    ticker_calls = {}

    def fake_resolve_ticker(symbol):
        ticker_calls["symbol"] = symbol
        return "JPY=X"

    monkeypatch.setattr(yfinance_fetch, "resolve_ticker", fake_resolve_ticker)

    fetch_calls = {}

    def fake_fetch(symbol, tf, *, start, end, **kwargs):
        fetch_calls["symbol"] = symbol
        fetch_calls["tf"] = tf
        fetch_calls["start"] = start
        fetch_calls["end"] = end
        fetch_calls["extra"] = kwargs
        yield {
            "timestamp": "2025-10-01T04:00:00",
            "symbol": symbol,
            "tf": tf,
            "o": 149.20,
            "h": 149.25,
            "l": 149.18,
            "c": 149.22,
            "v": 115.0,
            "spread": 0.0,
        }
        yield {
            "timestamp": "2025-10-01T04:05:00",
            "symbol": symbol,
            "tf": tf,
            "o": 149.22,
            "h": 149.27,
            "l": 149.20,
            "c": 149.25,
            "v": 118.0,
            "spread": 0.0,
        }

    monkeypatch.setattr(yfinance_fetch, "fetch_bars", fake_fetch)

    exit_code = run_daily_workflow.main(
        [
            "--ingest",
            "--use-yfinance",
            "--symbol",
            "JPY=X",
            "--mode",
            "conservative",
            "--yfinance-lookback-minutes",
            "45",
        ]
    )

    assert exit_code == 0
    assert ticker_calls["symbol"] == "JPY=X"
    assert fetch_calls["symbol"] == "JPY=X"
    assert fetch_calls["tf"] == "5m"
    last_ts = datetime.fromisoformat("2025-10-01T03:55:00")
    expected_start = last_ts - timedelta(minutes=45)
    assert fetch_calls["start"] == expected_start
    assert fetch_calls["end"] == fixed_now
    assert fetch_calls["extra"] == {}

    csv_lines = validated_csv.read_text(encoding="utf-8").splitlines()
    assert csv_lines[-1].startswith("2025-10-01T04:05:00")

    features_csv = repo_root / "features/JPY=X/5m.csv"
    assert features_csv.exists()

    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert snapshot["ingest"]["JPY=X_5m"] == "2025-10-01T04:05:00"
    meta = snapshot["ingest_meta"]["JPY=X_5m"]
    assert meta["primary_source"] == "yfinance"
    assert [entry["source"] for entry in meta["source_chain"]] == ["yfinance"]
    assert meta["rows_validated"] >= 2
    assert meta["freshness_minutes"] == pytest.approx(15.0)
    assert meta["synthetic_extension"] is False
    assert meta.get("fallbacks", []) == []
    assert meta["last_ingest_at"] == fixed_now.replace(tzinfo=timezone.utc).isoformat()
    assert not anomaly_log_path.exists()


def test_dukascopy_success_persists_offer_side_metadata(tmp_path, monkeypatch):
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

    fetch_calls = {}

    def fake_fetch(symbol, tf, *, start, end, offer_side):
        fetch_calls["symbol"] = symbol
        fetch_calls["tf"] = tf
        fetch_calls["start"] = start
        fetch_calls["end"] = end
        fetch_calls["offer_side"] = offer_side
        return iter(
            [
                {
                    "timestamp": "2025-10-01T04:00:00",
                    "symbol": symbol,
                    "tf": tf,
                    "o": 149.30,
                    "h": 149.35,
                    "l": 149.25,
                    "c": 149.32,
                    "v": 105.0,
                    "spread": 0.0,
                },
                {
                    "timestamp": "2025-10-01T04:05:00",
                    "symbol": symbol,
                    "tf": tf,
                    "o": 149.32,
                    "h": 149.38,
                    "l": 149.28,
                    "c": 149.36,
                    "v": 110.0,
                    "spread": 0.0,
                },
            ]
        )

    monkeypatch.setattr(
        ingest_providers,
        "resolve_dukascopy_fetch",
        lambda: (fake_fetch, None),
    )

    exit_code = run_daily_workflow.main(
        [
            "--ingest",
            "--use-dukascopy",
            "--symbol",
            "USDJPY",
            "--mode",
            "conservative",
            "--dukascopy-lookback-minutes",
            "30",
            "--dukascopy-offer-side",
            "ask",
        ]
    )

    assert exit_code == 0
    assert fetch_calls["symbol"] == "USDJPY"
    assert fetch_calls["tf"] == "5m"
    assert fetch_calls["offer_side"] == "ask"

    csv_lines = validated_csv.read_text(encoding="utf-8").splitlines()
    assert csv_lines[-1].startswith("2025-10-01T04:05:00")

    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert snapshot["ingest"]["USDJPY_5m"] == "2025-10-01T04:05:00"

    meta = snapshot["ingest_meta"]["USDJPY_5m"]
    assert meta["primary_source"] == "dukascopy"
    assert [entry["source"] for entry in meta["source_chain"]] == ["dukascopy"]
    assert meta["dukascopy_offer_side"] == "ask"
    assert meta["rows_validated"] >= 2
    assert meta["freshness_minutes"] == pytest.approx(15.0)
    assert meta.get("fallbacks") in (None, [])
    assert meta["synthetic_extension"] is False
    assert meta["last_ingest_at"] == fixed_now.replace(tzinfo=timezone.utc).isoformat()
    assert not anomaly_log_path.exists()


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

    def fake_fetch(symbol, tf, *, start, end, **kwargs):
        fallback_calls["symbol"] = symbol
        fallback_calls["tf"] = tf
        fallback_calls["start"] = start
        fallback_calls["end"] = end
        fallback_calls["extra"] = kwargs
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
    assert fallback_calls["extra"] == {}

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
    assert "dukascopy_offer_side" not in meta


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

    def _fail_resolve():
        return None, RuntimeError("dukascopy_python is required")

    monkeypatch.setattr(ingest_providers, "resolve_dukascopy_fetch", _fail_resolve)

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
    assert "dukascopy_offer_side" not in meta


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

    def _fail_resolve():
        return None, RuntimeError("dukascopy_python is required")

    monkeypatch.setattr(ingest_providers, "resolve_dukascopy_fetch", _fail_resolve)

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
    local_note = next(note for note in fallbacks if note["stage"] == "local_csv")
    assert Path(local_note["detail"]) == fallback_csv
    assert local_note.get("next_source") == "synthetic_local"
    assert meta["local_backup_path"] == str(fallback_csv)
    assert meta["last_ingest_at"] == fixed_now.replace(tzinfo=timezone.utc).isoformat()
    assert "dukascopy_offer_side" not in meta


@pytest.mark.parametrize("fallback_kind", ["yfinance", "local_csv"])
def test_dukascopy_fallback_metadata_excludes_offer_side(
    tmp_path, monkeypatch, fallback_kind
):
    repo_root = tmp_path / "repo"
    (repo_root / "ops/logs").mkdir(parents=True)
    (repo_root / "raw").mkdir()
    (repo_root / "validated/USDJPY").mkdir(parents=True)
    (repo_root / "features/USDJPY").mkdir(parents=True)
    if fallback_kind == "local_csv":
        (repo_root / "data").mkdir(parents=True, exist_ok=True)

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

    fallback_csv = None
    if fallback_kind == "local_csv":
        fallback_csv = repo_root / "data/usdjpy_5m_2018-2024_utc.csv"
        fallback_csv.write_text(
            "timestamp,symbol,tf,o,h,l,c,v,spread\n"
            "2025-10-01T04:00:00,USDJPY,5m,149.20,149.22,149.18,149.21,140,0\n"
            "2025-10-01T04:05:00,USDJPY,5m,149.21,149.25,149.19,149.24,145,0\n",
            encoding="utf-8",
        )

    from scripts import pull_prices

    anomaly_log_path = repo_root / "ops/logs/ingest_anomalies.jsonl"
    monkeypatch.setattr(pull_prices, "ANOMALY_LOG", anomaly_log_path)
    monkeypatch.setattr(run_daily_workflow, "ROOT", repo_root)

    fixed_now = datetime(2025, 10, 1, 4, 45)

    class _FixedDatetime(datetime):
        @classmethod
        def utcnow(cls):
            return fixed_now

        @classmethod
        def fromisoformat(cls, value):
            return datetime.fromisoformat(value)

    monkeypatch.setattr(run_daily_workflow, "datetime", _FixedDatetime)

    def _fail_resolve():
        return None, RuntimeError("dukascopy unavailable")

    monkeypatch.setattr(ingest_providers, "resolve_dukascopy_fetch", _fail_resolve)

    def fake_resolve(symbol):
        return "JPY=X"

    monkeypatch.setattr(yfinance_fetch, "resolve_ticker", fake_resolve)

    if fallback_kind == "yfinance":

        def fake_yf_fetch(symbol, tf, *, start, end):
            yield {
                "timestamp": "2025-10-01T04:00:00",
                "symbol": symbol,
                "tf": tf,
                "o": 149.20,
                "h": 149.23,
                "l": 149.18,
                "c": 149.21,
                "v": 150.0,
                "spread": 0.0,
            }
            yield {
                "timestamp": "2025-10-01T04:05:00",
                "symbol": symbol,
                "tf": tf,
                "o": 149.21,
                "h": 149.24,
                "l": 149.19,
                "c": 149.22,
                "v": 155.0,
                "spread": 0.0,
            }

        monkeypatch.setattr(yfinance_fetch, "fetch_bars", fake_yf_fetch)
    else:

        def failing_yf_fetch(*_args, **_kwargs):
            raise RuntimeError("yfinance unavailable")

        monkeypatch.setattr(yfinance_fetch, "fetch_bars", failing_yf_fetch)

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

    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    meta = snapshot["ingest_meta"]["USDJPY_5m"]
    assert "dukascopy_offer_side" not in meta
    chain_sources = [entry["source"] for entry in meta["source_chain"]]
    if fallback_kind == "yfinance":
        assert "yfinance" in chain_sources
    else:
        assert "local_csv" in chain_sources
        assert meta.get("local_backup_path") == str(fallback_csv)


def test_local_csv_fallback_can_disable_synthetic_extension(tmp_path, monkeypatch):
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

    def _fail_resolve():
        return None, RuntimeError("dukascopy_python is required")

    monkeypatch.setattr(ingest_providers, "resolve_dukascopy_fetch", _fail_resolve)

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
            "--disable-synthetic-extension",
        ]
    )

    assert exit_code == 0
    assert ingest_calls
    assert ingest_calls[0]["source_name"].startswith("local_csv:")
    assert len(ingest_calls[0]["rows"]) == 5
    assert all(call["source_name"] != "synthetic_local" for call in ingest_calls)

    csv_lines = validated_csv.read_text(encoding="utf-8").splitlines()
    assert csv_lines[-1].startswith("2025-10-03T04:20:00")

    features_csv = repo_root / "features/USDJPY/5m.csv"
    assert features_csv.exists()

    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert snapshot["ingest"]["USDJPY_5m"] == "2025-10-03T04:20:00"
    if anomaly_log_path.exists():
        assert anomaly_log_path.read_text(encoding="utf-8").strip() == ""

    meta = snapshot["ingest_meta"]["USDJPY_5m"]
    assert meta["primary_source"] == "dukascopy"
    chain = meta["source_chain"]
    assert chain == [{"source": "local_csv", "detail": fallback_csv.name}]
    assert meta["synthetic_extension"] is False
    assert meta["freshness_minutes"] == pytest.approx(10.0)
    fallbacks = meta["fallbacks"]
    local_note = next(note for note in fallbacks if note["stage"] == "local_csv")
    assert "next_source" not in local_note
    assert Path(local_note["detail"]) == fallback_csv
    assert meta["local_backup_path"] == str(fallback_csv)
    assert meta["last_ingest_at"] == fixed_now.replace(tzinfo=timezone.utc).isoformat()


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

    def _fail_resolve():
        return None, RuntimeError("dukascopy_python is required")

    monkeypatch.setattr(ingest_providers, "resolve_dukascopy_fetch", _fail_resolve)

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
    local_note = next(note for note in fallbacks if note["stage"] == "local_csv")
    assert Path(local_note["detail"]) == custom_csv
    assert snapshot["ingest_meta"]["USDJPY_5m"]["local_backup_path"] == str(
        custom_csv
    )
    assert "dukascopy_offer_side" not in snapshot["ingest_meta"]["USDJPY_5m"]


def test_local_csv_fallback_expands_user_path(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    (repo_root / "ops/logs").mkdir(parents=True)
    (repo_root / "raw").mkdir()
    (repo_root / "validated/USDJPY").mkdir(parents=True)
    (repo_root / "features/USDJPY").mkdir(parents=True)

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

    home_dir = tmp_path / "home"
    home_dir.mkdir()
    custom_csv = home_dir / "custom_backup.csv"
    custom_csv.write_text(
        "timestamp,symbol,tf,o,h,l,c,v,spread\n"
        "2025-10-03T04:00:00,USDJPY,5m,148.10,148.12,148.08,148.11,180,0\n"
        "2025-10-03T04:05:00,USDJPY,5m,148.12,148.14,148.10,148.13,175,0\n",
        encoding="utf-8",
    )

    from scripts import pull_prices

    anomaly_log_path = repo_root / "ops/logs/ingest_anomalies.jsonl"
    monkeypatch.setattr(pull_prices, "ANOMALY_LOG", anomaly_log_path)
    monkeypatch.setattr(run_daily_workflow, "ROOT", repo_root)
    monkeypatch.setenv("HOME", str(home_dir))

    fixed_now = datetime(2025, 10, 3, 4, 10)

    class _FixedDatetime(datetime):
        @classmethod
        def utcnow(cls):
            return fixed_now

    monkeypatch.setattr(run_daily_workflow, "datetime", _FixedDatetime)

    def _fail_resolve():
        return None, RuntimeError("dukascopy_python is required")

    monkeypatch.setattr(ingest_providers, "resolve_dukascopy_fetch", _fail_resolve)

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
            "~/custom_backup.csv",
        ]
    )

    assert exit_code == 0
    assert ingest_calls
    assert ingest_calls[0]["source_name"] == "local_csv:custom_backup.csv"

    csv_lines = validated_csv.read_text(encoding="utf-8").splitlines()
    assert csv_lines[-1].startswith("2025-10-03T04:05:00")

    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    meta = snapshot["ingest_meta"]["USDJPY_5m"]
    local_note = next(note for note in meta["fallbacks"] if note["stage"] == "local_csv")
    assert Path(local_note["detail"]) == custom_csv
    assert meta["local_backup_path"] == str(custom_csv)


def test_local_csv_fallback_missing_for_symbol_without_default(tmp_path, monkeypatch, capfd):
    repo_root = tmp_path / "repo"
    (repo_root / "ops/logs").mkdir(parents=True)
    (repo_root / "raw").mkdir()
    (repo_root / "validated/EURUSD").mkdir(parents=True)
    (repo_root / "features/EURUSD").mkdir(parents=True)
    (repo_root / "data").mkdir(parents=True)

    snapshot_path = repo_root / "ops/runtime_snapshot.json"
    snapshot_path.write_text(
        json.dumps({"ingest": {"EURUSD_5m": "2025-10-03T03:55:00"}}),
        encoding="utf-8",
    )

    validated_csv = repo_root / "validated/EURUSD/5m.csv"
    validated_csv.write_text(
        "timestamp,symbol,tf,o,h,l,c,v,spread\n"
        "2025-10-03T03:55:00,EURUSD,5m,1.054,1.055,1.053,1.054,120,0\n",
        encoding="utf-8",
    )

    from scripts import pull_prices

    anomaly_log_path = repo_root / "ops/logs/ingest_anomalies.jsonl"
    monkeypatch.setattr(pull_prices, "ANOMALY_LOG", anomaly_log_path)
    monkeypatch.setattr(run_daily_workflow, "ROOT", repo_root)

    def _fail_resolve():
        return None, RuntimeError("dukascopy unavailable")

    monkeypatch.setattr(ingest_providers, "resolve_dukascopy_fetch", _fail_resolve)

    def _missing_yfinance(*_args, **_kwargs):
        raise RuntimeError("missing yfinance dependency")

    monkeypatch.setattr(yfinance_fetch, "fetch_bars", _missing_yfinance)

    def _ingest_should_not_run(*_args, **_kwargs):
        pytest.fail("ingest_records should not run when no local CSV exists")

    monkeypatch.setattr(pull_prices, "ingest_records", _ingest_should_not_run)

    exit_code = run_daily_workflow.main(
        [
            "--ingest",
            "--use-dukascopy",
            "--symbol",
            "EURUSD",
            "--mode",
            "conservative",
            "--disable-synthetic-extension",
        ]
    )

    assert exit_code == 1
    captured = capfd.readouterr()
    expected_path = (repo_root / "data/eurusd_5m_2018-2024_utc.csv").resolve()
    assert "local CSV fallback triggered" in captured.out
    assert f"local CSV backup not found for symbol EURUSD: expected {expected_path}" in captured.out
    if anomaly_log_path.exists():
        assert anomaly_log_path.read_text(encoding="utf-8").strip() == ""


def test_local_csv_fallback_uses_custom_backup_for_non_usdjpy(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    (repo_root / "ops/logs").mkdir(parents=True)
    (repo_root / "raw").mkdir()
    (repo_root / "validated/EURUSD").mkdir(parents=True)
    (repo_root / "features/EURUSD").mkdir(parents=True)
    (repo_root / "data").mkdir(parents=True)

    snapshot_path = repo_root / "ops/runtime_snapshot.json"
    snapshot_path.write_text(
        json.dumps({"ingest": {"EURUSD_5m": "2025-10-03T03:55:00"}}),
        encoding="utf-8",
    )

    validated_csv = repo_root / "validated/EURUSD/5m.csv"
    validated_csv.write_text(
        "timestamp,symbol,tf,o,h,l,c,v,spread\n"
        "2025-10-03T03:55:00,EURUSD,5m,1.054,1.055,1.053,1.054,120,0\n",
        encoding="utf-8",
    )

    custom_csv = repo_root / "data/eurusd_backup.csv"
    custom_csv.write_text(
        "timestamp,symbol,tf,o,h,l,c,v,spread\n"
        "2025-10-03T04:00:00,EURUSD,5m,1.055,1.056,1.054,1.055,140,0\n"
        "2025-10-03T04:05:00,EURUSD,5m,1.056,1.057,1.055,1.056,150,0\n",
        encoding="utf-8",
    )

    from scripts import pull_prices

    anomaly_log_path = repo_root / "ops/logs/ingest_anomalies.jsonl"
    monkeypatch.setattr(pull_prices, "ANOMALY_LOG", anomaly_log_path)
    monkeypatch.setattr(run_daily_workflow, "ROOT", repo_root)

    def _fail_resolve():
        return None, RuntimeError("dukascopy unavailable")

    monkeypatch.setattr(ingest_providers, "resolve_dukascopy_fetch", _fail_resolve)

    def _missing_yfinance(*_args, **_kwargs):
        raise RuntimeError("missing yfinance dependency")

    monkeypatch.setattr(yfinance_fetch, "fetch_bars", _missing_yfinance)

    ingest_calls = []
    original_ingest = pull_prices.ingest_records

    def _tracking_ingest(records, **kwargs):
        rows = list(records)
        ingest_calls.append({"rows": rows, "source_name": kwargs.get("source_name")})
        return original_ingest(rows, **kwargs)

    monkeypatch.setattr(pull_prices, "ingest_records", _tracking_ingest)

    exit_code = run_daily_workflow.main(
        [
            "--ingest",
            "--use-dukascopy",
            "--symbol",
            "EURUSD",
            "--mode",
            "conservative",
            "--local-backup-csv",
            "data/eurusd_backup.csv",
            "--disable-synthetic-extension",
        ]
    )

    assert exit_code == 0
    assert ingest_calls
    assert ingest_calls[0]["source_name"] == "local_csv:eurusd_backup.csv"

    csv_lines = validated_csv.read_text(encoding="utf-8").splitlines()
    assert csv_lines[-1].startswith("2025-10-03T04:05:00")

    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    meta = snapshot["ingest_meta"]["EURUSD_5m"]
    chain = meta["source_chain"]
    assert chain == [{"source": "local_csv", "detail": "eurusd_backup.csv"}]
    fallbacks = meta["fallbacks"]
    local_note = next(note for note in fallbacks if note["stage"] == "local_csv")
    assert Path(local_note["detail"]) == custom_csv
    assert meta["local_backup_path"] == str(custom_csv)


def test_extend_with_synthetic_bars_skips_when_latest_fresh(tmp_path):
    validated_path = tmp_path / "validated.csv"
    validated_path.write_text(
        "timestamp,symbol,tf,o,h,l,c,v,spread\n"
        "2025-10-02T03:55:00,USDJPY,5m,147.9,147.95,147.85,147.92,110,0\n",
        encoding="utf-8",
    )

    base_result = {
        "source": "local_csv:backup.csv",
        "rows_validated": 5,
        "rows_raw": 5,
        "rows_featured": 5,
        "anomalies_logged": 0,
        "gaps_detected": 0,
        "last_ts_now": "2025-10-02T04:10:00",
    }

    ingest_calls = []

    def fake_ingest(records, **kwargs):
        rows = list(records)
        ingest_calls.append({"source_name": kwargs.get("source_name"), "rows": rows})
        last_ts = rows[-1]["timestamp"] if rows else base_result["last_ts_now"]
        return {
            "source": kwargs.get("source_name"),
            "rows_validated": len(rows),
            "rows_raw": len(rows),
            "rows_featured": len(rows),
            "anomalies_logged": 0,
            "gaps_detected": 0,
            "last_ts_now": last_ts,
        }

    result = run_daily_workflow._extend_with_synthetic_bars(
        base_result=dict(base_result),
        ingest_records_func=fake_ingest,
        symbol="USDJPY",
        tf="5m",
        snapshot_path=tmp_path / "snapshot.json",
        raw_path=tmp_path / "raw.csv",
        validated_path=validated_path,
        features_path=tmp_path / "features.csv",
        tf_minutes=5,
        now=datetime(2025, 10, 2, 4, 15),
    )

    assert ingest_calls == []
    assert result["last_ts_now"] == base_result["last_ts_now"]
    assert result["source"] == base_result["source"]


def test_extend_with_synthetic_bars_generates_when_stale(tmp_path):
    validated_path = tmp_path / "validated.csv"
    validated_path.write_text(
        "timestamp,symbol,tf,o,h,l,c,v,spread\n"
        "2025-10-02T03:55:00,USDJPY,5m,147.9,147.95,147.85,147.92,110,0\n",
        encoding="utf-8",
    )

    base_result = {
        "source": "local_csv:backup.csv",
        "rows_validated": 5,
        "rows_raw": 5,
        "rows_featured": 5,
        "anomalies_logged": 0,
        "gaps_detected": 0,
        "last_ts_now": "2025-10-02T03:55:00",
        "local_backup_path": str(tmp_path / "backup.csv"),
    }

    ingest_calls = []

    def fake_ingest(records, **kwargs):
        rows = list(records)
        ingest_calls.append({"source_name": kwargs.get("source_name"), "rows": rows})
        last_ts = rows[-1]["timestamp"] if rows else base_result["last_ts_now"]
        return {
            "source": kwargs.get("source_name"),
            "rows_validated": len(rows),
            "rows_raw": len(rows),
            "rows_featured": len(rows),
            "anomalies_logged": 0,
            "gaps_detected": 0,
            "last_ts_now": last_ts,
        }

    result = run_daily_workflow._extend_with_synthetic_bars(
        base_result=dict(base_result),
        ingest_records_func=fake_ingest,
        symbol="USDJPY",
        tf="5m",
        snapshot_path=tmp_path / "snapshot.json",
        raw_path=tmp_path / "raw.csv",
        validated_path=validated_path,
        features_path=tmp_path / "features.csv",
        tf_minutes=5,
        now=datetime(2025, 10, 2, 4, 20),
    )

    assert ingest_calls
    synthetic_call = ingest_calls[-1]
    assert synthetic_call["source_name"] == "synthetic_local"
    assert [row["timestamp"] for row in synthetic_call["rows"]] == [
        "2025-10-02T04:00:00",
        "2025-10-02T04:05:00",
        "2025-10-02T04:10:00",
        "2025-10-02T04:15:00",
    ]
    assert result["source"].endswith("synthetic_local")
    assert result["rows_validated"] == base_result["rows_validated"] + 4
    assert result["last_ts_now"] == "2025-10-02T04:15:00"
    assert result["local_backup_path"] == base_result["local_backup_path"]


def test_ingest_providers_fetch_dukascopy_records_stale_guard():
    start = datetime(2025, 1, 1, 0, 0)
    end = datetime(2025, 1, 1, 0, 30)
    stale_ts = (end - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%S")

    fetch_args = {}

    def fake_fetch(symbol, tf, *, start: datetime, end: datetime, offer_side: str):
        fetch_args.update(
            {
                "symbol": symbol,
                "tf": tf,
                "start": start,
                "end": end,
                "offer_side": offer_side,
            }
        )
        return [
            {"timestamp": stale_ts, "symbol": symbol, "tf": tf},
        ]

    with pytest.raises(ingest_providers.ProviderError) as excinfo:
        ingest_providers.fetch_dukascopy_records(
            fake_fetch,
            "USDJPY",
            "5m",
            start=start,
            end=end,
            offer_side="bid",
            init_error=None,
            freshness_threshold=5,
        )

    assert "stale data" in str(excinfo.value)
    assert fetch_args["symbol"] == "USDJPY"
    assert fetch_args["tf"] == "5m"
    assert fetch_args["offer_side"] == "bid"


def test_ingest_providers_yfinance_fallback_runner_handles_import_error():
    ctx = SimpleNamespace(symbol="USDJPY", tf="5m")
    args = SimpleNamespace(symbol="USDJPY", yfinance_lookback_minutes=60)
    now = datetime(2025, 1, 1, 1, 0)
    last_ts = datetime(2025, 1, 1, 0, 30)

    ingest_calls = []

    def fake_ingest(**kwargs):
        ingest_calls.append(kwargs)
        with pytest.raises(ingest_providers.ProviderError):
            list(kwargs["fetch_records"]())
        return None, None

    def failing_loader():
        raise RuntimeError("missing dependency")

    runner = ingest_providers.YFinanceFallbackRunner(
        ctx,
        args,
        now=now,
        last_ts=last_ts,
        ingest_runner=fake_ingest,
        yfinance_loader=failing_loader,
    )

    result = runner("dukascopy outage")

    assert result == (None, None)
    assert ingest_calls
    call = ingest_calls[0]
    assert call["stage"] == "yfinance"
    assert call["source_label"] == "yfinance"


def test_run_daily_workflow_uses_shared_timestamp_parser():
    from scripts import _time_utils

    parser = run_daily_workflow._parse_naive_utc

    assert parser is _time_utils.parse_naive_utc

    dt_z = parser("2024-01-01T00:00:00Z")
    assert dt_z == datetime(2024, 1, 1, 0, 0)
    assert dt_z.tzinfo is None

    dt_offset = parser("2024-01-01T09:00:00+09:00")
    assert dt_offset == datetime(2024, 1, 1, 0, 0)
    assert dt_offset.tzinfo is None

    assert parser("   ") is None
    assert parser("not-a-timestamp") is None
