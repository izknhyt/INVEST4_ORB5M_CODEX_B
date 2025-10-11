from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from scripts import summarize_runs
from scripts import _automation_logging
from scripts._webhook import WebhookDeliveryResult, sign_payload


def _write_runs_index(path: Path, rows: List[Dict[str, Any]]) -> None:
    headers = [
        "run_id",
        "run_dir",
        "timestamp",
        "symbol",
        "mode",
        "equity",
        "or_n",
        "k_tp",
        "k_sl",
        "threshold_lcb",
        "min_or_atr",
        "allow_low_rv",
        "allowed_sessions",
        "warmup",
        "trades",
        "wins",
        "total_pips",
    ]
    lines = [",".join(headers)]
    for row in rows:
        lines.append(
            ",".join(
                str(row.get(header, ""))
                for header in headers
            )
        )
    path.write_text("\n".join(lines), encoding="utf-8")


@pytest.fixture
def sample_environment(tmp_path: Path) -> summarize_runs.SummaryPaths:
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    ops_dir = tmp_path / "ops" / "health"
    ops_dir.mkdir(parents=True)

    _write_runs_index(
        runs_root / "index.csv",
        [
            {
                "run_id": "run_a",
                "run_dir": "runs/run_a",
                "timestamp": "20250101_000000",
                "symbol": "USDJPY",
                "mode": "conservative",
                "equity": 100000,
                "or_n": 4,
                "k_tp": 0.8,
                "k_sl": 0.6,
                "threshold_lcb": 0.0,
                "allow_low_rv": True,
                "warmup": 40,
                "trades": 120,
                "wins": 70,
                "total_pips": 180.5,
            },
            {
                "run_id": "run_b",
                "run_dir": "runs/run_b",
                "timestamp": "20250102_000000",
                "symbol": "USDJPY",
                "mode": "conservative",
                "equity": 100000,
                "or_n": 6,
                "k_tp": 1.0,
                "k_sl": 0.8,
                "threshold_lcb": 0.0,
                "allow_low_rv": False,
                "warmup": 60,
                "trades": 80,
                "wins": 45,
                "total_pips": 92.0,
            },
            {
                "run_id": "run_c",
                "run_dir": "runs/run_c",
                "timestamp": "20250103_000000",
                "symbol": "EURUSD",
                "mode": "bridge",
                "equity": 100000,
                "or_n": 5,
                "k_tp": 0.9,
                "k_sl": 0.7,
                "threshold_lcb": 0.0,
                "allow_low_rv": True,
                "warmup": 30,
                "trades": 60,
                "wins": 32,
                "total_pips": -35.0,
            },
        ],
    )

    benchmark_payload = {
        "generated_at": "2025-01-04T00:00:00Z",
        "symbol": "USDJPY",
        "mode": "conservative",
        "baseline": {
            "trades": 300,
            "wins": 180,
            "win_rate": 0.6,
            "total_pips": 250.0,
            "sharpe": 1.1,
            "max_drawdown": -80.0,
        },
        "rolling": [
            {
                "window": 365,
                "trades": 120,
                "wins": 72,
                "win_rate": 0.6,
                "total_pips": 80.0,
                "sharpe": 0.9,
                "max_drawdown": -50.0,
            },
            {
                "window": 90,
                "trades": 40,
                "wins": 30,
                "win_rate": 0.75,
                "total_pips": 110.0,
                "sharpe": 1.5,
                "max_drawdown": -10.0,
            },
        ],
        "warnings": ["rolling 90d Sharpe above expectation"],
        "threshold_alerts": [],
    }
    (reports_dir / "benchmark_summary.json").write_text(
        json.dumps(benchmark_payload),
        encoding="utf-8",
    )

    portfolio_payload = {
        "generated_at": "2025-01-04T00:00:00Z",
        "category_utilisation": [
            {
                "category": "day",
                "utilisation_pct": 35.0,
                "cap_pct": 50.0,
                "headroom_pct": 15.0,
                "utilisation_ratio": 0.7,
            },
            {
                "category": "scalping",
                "utilisation_pct": 18.0,
                "cap_pct": 20.0,
                "headroom_pct": 2.0,
                "utilisation_ratio": 0.9,
            },
            {
                "category": "swing",
                "utilisation_pct": 22.0,
                "cap_pct": 20.0,
                "headroom_pct": -2.0,
                "utilisation_ratio": 1.1,
            },
        ],
        "gross_exposure": {
            "current_pct": 60.0,
            "cap_pct": 80.0,
            "headroom_pct": 20.0,
        },
    }
    (reports_dir / "portfolio_summary.json").write_text(
        json.dumps(portfolio_payload),
        encoding="utf-8",
    )

    state_checks = [
        {
            "checked_at": "2025-01-03T10:00:00Z",
            "state_path": "/tmp/state.json",
            "metrics": {"ev_total_samples": 120.0},
            "warnings": ["bucket LDN:narrow:low samples=2.0 below threshold"],
        },
        {
            "checked_at": "2025-01-04T10:15:00Z",
            "state_path": "/tmp/state.json",
            "metrics": {"ev_total_samples": 140.0},
            "warnings": [],
        },
    ]
    (ops_dir / "state_checks.json").write_text(
        json.dumps(state_checks),
        encoding="utf-8",
    )

    return summarize_runs.SummaryPaths(
        runs_root=runs_root,
        benchmark_summary=reports_dir / "benchmark_summary.json",
        portfolio_summary=reports_dir / "portfolio_summary.json",
        health_checks=ops_dir / "state_checks.json",
    )


@pytest.fixture
def _patch_weekly_automation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    log_path = tmp_path / "ops/automation_runs.log"
    seq_path = tmp_path / "ops/automation_runs.sequence"
    monkeypatch.setattr(_automation_logging, "AUTOMATION_LOG_PATH", log_path)
    monkeypatch.setattr(_automation_logging, "AUTOMATION_SEQUENCE_PATH", seq_path)

    def _log_with_paths(*args, **kwargs):
        kwargs.setdefault("log_path", log_path)
        kwargs.setdefault("sequence_path", seq_path)
        return _automation_logging.log_automation_event_with_sequence(*args, **kwargs)

    monkeypatch.setattr(summarize_runs, "log_automation_event_with_sequence", _log_with_paths)
    return log_path


def test_build_summary_with_all_components(sample_environment: summarize_runs.SummaryPaths) -> None:
    payload = summarize_runs.build_summary(
        sample_environment,
        [
            summarize_runs.COMPONENT_RUNS,
            summarize_runs.COMPONENT_BENCHMARKS,
            summarize_runs.COMPONENT_PORTFOLIO,
            summarize_runs.COMPONENT_HEALTH,
        ],
        generated_at="2025-01-05T00:00:00+00:00",
    )

    assert payload["generated_at"] == "2025-01-05T00:00:00+00:00"
    runs_component = payload["components"][summarize_runs.COMPONENT_RUNS]
    assert runs_component["totals"]["trades"] == 260
    assert runs_component["totals"]["wins"] == 147
    assert pytest.approx(runs_component["totals"]["win_rate"], rel=1e-9) == 147 / 260
    assert runs_component["top_runs"][0]["run_id"] == "run_a"

    benchmark_component = payload["components"][summarize_runs.COMPONENT_BENCHMARKS]
    assert benchmark_component["status"] == "warning"
    rolling_windows = [entry["window"] for entry in benchmark_component["rolling"]]
    assert rolling_windows == [90, 365]

    portfolio_component = payload["components"][summarize_runs.COMPONENT_PORTFOLIO]
    statuses = {entry["category"]: entry["status"] for entry in portfolio_component["category_utilisation"]}
    assert statuses == {"day": "ok", "scalping": "warning", "swing": "breach"}

    health_component = payload["components"][summarize_runs.COMPONENT_HEALTH]
    assert health_component["status"] == "ok"
    assert health_component["latest"]["warning_count"] == 0
    assert health_component["recent"][0]["warning_count"] == 1


def test_build_summary_respects_includes(sample_environment: summarize_runs.SummaryPaths) -> None:
    payload = summarize_runs.build_summary(
        sample_environment,
        [summarize_runs.COMPONENT_BENCHMARKS, summarize_runs.COMPONENT_HEALTH],
        generated_at="2025-01-05T00:00:00+00:00",
    )
    assert summarize_runs.COMPONENT_RUNS not in payload["components"]
    assert summarize_runs.COMPONENT_PORTFOLIO not in payload["components"]
    assert summarize_runs.COMPONENT_BENCHMARKS in payload["components"]
    assert summarize_runs.COMPONENT_HEALTH in payload["components"]


def test_dispatch_webhooks_posts_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: Dict[str, Any] = {}

    class DummyResponse:
        status = 204

        def read(self) -> bytes:
            return b""

        def __enter__(self) -> "DummyResponse":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    def fake_urlopen(request, timeout: float = 0.0):  # type: ignore[no-untyped-def]
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["headers"] = {name.lower(): value for name, value in request.header_items()}
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return DummyResponse()

    monkeypatch.setattr(summarize_runs, "urlopen", fake_urlopen)

    payload = {
        "type": "benchmark_weekly_summary",
        "generated_at": "2025-01-05T00:00:00+00:00",
        "components": {},
    }
    destinations = [
        {
            "url": "http://example.test/webhook",
            "timeout": 3.0,
            "headers": {"X-Test": "1"},
        }
    ]

    results = summarize_runs.dispatch_webhooks(payload, destinations)

    assert results[0]["status"] == "ok"
    assert captured["url"] == "http://example.test/webhook"
    assert captured["timeout"] == 3.0
    assert captured["headers"]["content-type"] == "application/json"
    assert captured["headers"]["x-test"] == "1"
    assert captured["body"]["type"] == "benchmark_weekly_summary"


def test_weekly_payload_cli_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    _patch_weekly_automation: Path,
) -> None:
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    _write_runs_index(
        runs_root / "index.csv",
        [
            {
                "run_id": "run_weekly",
                "run_dir": "runs/run_weekly",
                "timestamp": "20260701_010000",
                "symbol": "USDJPY",
                "mode": "conservative",
                "equity": 100000,
                "or_n": 4,
                "k_tp": 0.6,
                "k_sl": 0.4,
                "threshold_lcb": 0.0,
                "min_or_atr": "",
                "allow_low_rv": True,
                "allowed_sessions": "all",
                "warmup": 40,
                "trades": 120,
                "wins": 70,
                "total_pips": 150.5,
            }
        ],
    )

    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    (reports_dir / "benchmark_summary.json").write_text("{}", encoding="utf-8")
    portfolio_payload = {
        "generated_at": "2026-06-29T00:00:00Z",
        "category_utilisation": [
            {"category": "day", "budget_status": "ok", "utilisation_pct": 30.0, "headroom_pct": 10.0},
            {"category": "swing", "budget_status": "warning", "utilisation_pct": 20.0, "headroom_pct": 5.0},
        ],
        "gross_exposure": {"current_pct": 40.0, "headroom_pct": 20.0},
        "drawdowns": {"aggregate": {"max_drawdown_pct": 2.0}},
    }
    portfolio_path = reports_dir / "portfolio_summary.json"
    portfolio_path.write_text(json.dumps(portfolio_payload), encoding="utf-8")

    latency_dir = tmp_path / "ops"
    latency_dir.mkdir()
    latency_path = latency_dir / "signal_latency_rollup.csv"
    latency_path.write_text(
        "hour_utc,window_end_utc,count,failure_count,failure_rate,p50_ms,p95_ms,p99_ms,max_ms\n"
        "2026-06-29T00:00:00Z,2026-06-29T01:00:00Z,10,1,0.1,120,450,470,500\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("OBS_WEEKLY_WEBHOOK_URL", "https://example.test/webhook")
    monkeypatch.setenv("OBS_WEEKLY_WEBHOOK_SECRET", "weeklysecret")

    def fake_deliver(url, payload, **kwargs):  # type: ignore[no-untyped-def]
        return WebhookDeliveryResult(url=url, status="ok", attempts=1, status_code=200, response_ms=125.0)

    monkeypatch.setattr(summarize_runs, "deliver_webhook", fake_deliver)

    history_dir = tmp_path / "history"
    dry_dir = tmp_path / "dry"

    args = [
        "--weekly-payload",
        "--runs-root",
        str(runs_root),
        "--portfolio-summary",
        str(portfolio_path),
        "--latency-rollup",
        str(latency_path),
        "--benchmark-summary",
        str(reports_dir / "benchmark_summary.json"),
        "--job-id",
        "20260701T000000Z-weekly",
        "--job-name",
        "weekly-test",
        "--out-dir",
        str(history_dir),
        "--dry-run-dir",
        str(dry_dir),
        "--webhook-url-env",
        "OBS_WEEKLY_WEBHOOK_URL",
        "--webhook-secret-env",
        "OBS_WEEKLY_WEBHOOK_SECRET",
        "--json-out",
        str(tmp_path / "summary.json"),
    ]

    exit_code = summarize_runs.main(args)
    assert exit_code == 0

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "ok"
    week_start = output["week_start"]
    history_path = history_dir / f"{week_start}.json"
    assert history_path.exists()
    log_entries = _patch_weekly_automation.read_text(encoding="utf-8").strip().splitlines()
    assert log_entries and "20260701T000000Z-weekly" in log_entries[-1]

    summary_data = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary_data["payload_checksum_sha256"]

    signature_path = history_dir / f"{week_start}.sig"
    signature = signature_path.read_text(encoding="utf-8").strip()
    payload_bytes = json.dumps(json.loads(history_path.read_text(encoding="utf-8")), ensure_ascii=False).encode(
        "utf-8"
    )
    assert signature == sign_payload(payload_bytes, "weeklysecret")
