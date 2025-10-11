from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from analysis import weekly_payload
from analysis.weekly_payload import LatencyRollupEntry, WeeklyPayloadContext, build
from scripts.utils_runs import RunRecord


def _make_run(**overrides) -> RunRecord:
    base = {
        "run_id": "run_a",
        "run_dir": "runs/run_a",
        "timestamp": "20260701_010000",
        "symbol": "USDJPY",
        "mode": "conservative",
        "equity": 100000.0,
        "or_n": 4,
        "k_tp": 0.6,
        "k_sl": 0.4,
        "threshold_lcb": 0.0,
        "min_or_atr": None,
        "allow_low_rv": True,
        "allowed_sessions": "all",
        "warmup": 40,
        "trades": 120,
        "wins": 70,
        "total_pips": 150.5,
        "sharpe": 1.23,
        "max_drawdown": -50.0,
        "pnl_per_trade": 1.2,
    }
    base.update(overrides)
    return RunRecord(**base)


def _make_rollup(hours_offset: int, p95: float, failures: int = 0) -> LatencyRollupEntry:
    start = datetime(2026, 6, 30, 0, 0, tzinfo=timezone.utc) + timedelta(hours=hours_offset)
    return LatencyRollupEntry(
        window_start=start,
        window_end=start + timedelta(hours=1),
        count=10,
        failure_count=failures,
        failure_rate=float(failures) / 10.0,
        p50_ms=120.0,
        p95_ms=p95,
        p99_ms=p95 + 20.0,
        max_ms=p95 + 40.0,
    )


def test_build_weekly_payload_sections(tmp_path: Path) -> None:
    runs = [_make_run(), _make_run(run_id="run_b", timestamp="20260702_030000", total_pips=200.0)]
    portfolio = {
        "generated_at": "2026-06-29T00:00:00Z",
        "category_utilisation": [
            {"category": "day", "budget_status": "ok", "utilisation_pct": 30.0, "headroom_pct": 10.0},
            {"category": "scalping", "budget_status": "warning", "utilisation_pct": 15.0, "headroom_pct": 5.0},
        ],
        "gross_exposure": {"current_pct": 40.0, "headroom_pct": 20.0},
        "drawdowns": {"aggregate": {"max_drawdown_pct": 3.2}},
    }
    latency = [
        _make_rollup(0, 450.0, failures=1),
        _make_rollup(5, 600.0, failures=2),
    ]
    context = WeeklyPayloadContext(
        runs=runs,
        portfolio=portfolio,
        latency_rollups=latency,
        as_of=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
        sources={"runs_index": "runs/index.csv"},
        metadata={"automation": {"job_id": "20260701T000000Z-weekly"}},
    )

    payload = build(context)
    payload.ensure_complete()
    data = payload.to_dict()

    assert data["schema_version"] == weekly_payload.SCHEMA_VERSION
    assert data["week_start"] == "2026-06-29"
    assert data["latency"]["breach_count"] == 2
    assert any(alert["id"] == "latency_breach" for alert in data["alerts"])
    assert any(alert["id"] == "portfolio_budget" for alert in data["alerts"])
    assert data["runs"][0]["run_id"] == "run_b"


def test_load_latency_rollups_parses_csv(tmp_path: Path) -> None:
    csv_path = tmp_path / "rollup.csv"
    csv_path.write_text(
        "hour_utc,window_end_utc,count,failure_count,failure_rate,p50_ms,p95_ms,p99_ms,max_ms\n"
        "2026-06-29T00:00:00Z,2026-06-29T01:00:00Z,5,1,0.2,100,200,250,300\n",
        encoding="utf-8",
    )

    entries = weekly_payload.load_latency_rollups(csv_path)

    assert len(entries) == 1
    entry = entries[0]
    assert entry.window_start == datetime(2026, 6, 29, 0, 0, tzinfo=timezone.utc)
    assert entry.failure_count == 1
