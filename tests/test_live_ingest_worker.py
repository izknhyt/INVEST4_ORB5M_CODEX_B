import csv
from datetime import datetime
from pathlib import Path
from typing import List

import pytest

from scripts import ingest_providers, live_ingest_worker as worker


@pytest.fixture(autouse=True)
def _patch_anomaly_log(monkeypatch, tmp_path):
    anomaly_log = tmp_path / "ops/logs/ingest_anomalies.jsonl"
    monkeypatch.setattr("scripts.pull_prices.ANOMALY_LOG", anomaly_log)
    return anomaly_log


def _read_validated(path: Path) -> List[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        return list(reader)


def test_live_worker_ingests_without_duplicates(monkeypatch, tmp_path):
    records_seq = [
        [
            {
                "timestamp": "2024-01-01T00:00:00",
                "symbol": "USDJPY",
                "tf": "5m",
                "o": 150.0,
                "h": 150.2,
                "l": 149.9,
                "c": 150.1,
                "v": 1200.0,
                "spread": 0.1,
            },
            {
                "timestamp": "2024-01-01T00:05:00",
                "symbol": "USDJPY",
                "tf": "5m",
                "o": 150.1,
                "h": 150.4,
                "l": 150.0,
                "c": 150.3,
                "v": 900.0,
                "spread": 0.1,
            },
        ],
        [
            {
                "timestamp": "2024-01-01T00:05:00",
                "symbol": "USDJPY",
                "tf": "5m",
                "o": 150.1,
                "h": 150.4,
                "l": 150.0,
                "c": 150.3,
                "v": 900.0,
                "spread": 0.1,
            },
            {
                "timestamp": "2024-01-01T00:10:00",
                "symbol": "USDJPY",
                "tf": "5m",
                "o": 150.3,
                "h": 150.6,
                "l": 150.2,
                "c": 150.5,
                "v": 800.0,
                "spread": 0.1,
            },
        ],
    ]
    duk_calls = []

    def fake_dukascopy(symbol, tf, *, start, end, offer_side, freshness_threshold=None):
        idx = min(len(duk_calls), len(records_seq) - 1)
        duk_calls.append((symbol, start, end, offer_side))
        return list(records_seq[idx])

    monkeypatch.setattr(worker, "_load_dukascopy_records", fake_dukascopy)
    monkeypatch.setattr(worker, "_load_yfinance_records", lambda *a, **k: [])

    updates = []

    def fake_update(symbol, mode, *, bars_path):
        updates.append((symbol, mode, Path(bars_path)))

    monkeypatch.setattr(worker, "_run_update_state", fake_update)

    args = [
        "--symbols",
        "USDJPY",
        "--modes",
        "conservative",
        "--interval",
        "0",
        "--max-iterations",
        "2",
        "--raw-root",
        str(tmp_path / "raw"),
        "--validated-root",
        str(tmp_path / "validated"),
        "--features-root",
        str(tmp_path / "features"),
        "--snapshot",
        str(tmp_path / "ops/runtime_snapshot.json"),
        "--shutdown-file",
        "",
        "--freshness-threshold-minutes",
        "0",
        "--lookback-minutes",
        "5",
    ]

    exit_code = worker.main(args)
    assert exit_code == 0

    validated_path = tmp_path / "validated" / "USDJPY" / "5m.csv"
    rows = _read_validated(validated_path)
    timestamps = [row["timestamp"] for row in rows]
    assert timestamps == [
        "2024-01-01T00:00:00",
        "2024-01-01T00:05:00",
        "2024-01-01T00:10:00",
    ]
    assert len(updates) == 2
    assert all(call[3] == "bid" for call in duk_calls)


def test_live_worker_fallback_to_yfinance(monkeypatch, tmp_path):
    def fail_fetch(*_args, **_kwargs):
        raise ingest_providers.ProviderError("no rows returned")

    monkeypatch.setattr(worker, "_load_dukascopy_records", fail_fetch)

    def fake_yfinance(symbol, tf, start, end):
        ts = (end - worker.timedelta(minutes=5)).replace(microsecond=0)
        return [
            {
                "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%S"),
                "symbol": symbol,
                "tf": tf,
                "o": 151.0,
                "h": 151.2,
                "l": 150.8,
                "c": 151.1,
                "v": 700.0,
                "spread": 0.1,
            }
        ]

    monkeypatch.setattr(worker, "_load_yfinance_records", fake_yfinance)

    updates = []

    def fake_update(symbol, mode, *, bars_path):
        updates.append((symbol, mode, Path(bars_path)))

    monkeypatch.setattr(worker, "_run_update_state", fake_update)

    args = [
        "--symbols",
        "USDJPY",
        "--modes",
        "conservative",
        "--interval",
        "0",
        "--max-iterations",
        "1",
        "--raw-root",
        str(tmp_path / "raw"),
        "--validated-root",
        str(tmp_path / "validated"),
        "--features-root",
        str(tmp_path / "features"),
        "--snapshot",
        str(tmp_path / "ops/runtime_snapshot.json"),
        "--shutdown-file",
        "",
        "--freshness-threshold-minutes",
        "90",
        "--lookback-minutes",
        "5",
    ]

    exit_code = worker.main(args)
    assert exit_code == 0

    validated_path = tmp_path / "validated" / "USDJPY" / "5m.csv"
    rows = _read_validated(validated_path)
    assert len(rows) == 1
    assert updates == [("USDJPY", "conservative", validated_path)]


def test_ingest_symbol_stale_triggers_yfinance(monkeypatch, tmp_path):
    stale_reason = "stale data: last_ts=2024-01-01T00:20:00"

    def stale_fetch(*args, **kwargs):
        raise ingest_providers.ProviderError(stale_reason)

    monkeypatch.setattr(worker, "_load_dukascopy_records", stale_fetch)

    fallback_calls = {}

    def fake_yfinance(symbol, tf, start, end):
        fallback_calls.update({
            "symbol": symbol,
            "tf": tf,
            "start": start,
            "end": end,
        })
        ts = (end - worker.timedelta(minutes=5)).replace(microsecond=0)
        return [
            {
                "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%S"),
                "symbol": symbol,
                "tf": tf,
                "o": 151.0,
                "h": 151.2,
                "l": 150.8,
                "c": 151.1,
                "v": 700.0,
                "spread": 0.1,
            }
        ]

    monkeypatch.setattr(worker, "_load_yfinance_records", fake_yfinance)
    last_processed = datetime(2024, 1, 1, 0, 15)
    monkeypatch.setattr(worker, "get_last_processed_ts", lambda *a, **k: last_processed)

    ingests = []

    def fake_ingest(records, **kwargs):
        rows = list(records)
        ingests.append({
            "rows": rows,
            "source_name": kwargs.get("source_name"),
        })
        return {
            "rows_validated": len(rows),
            "anomalies_logged": 0,
            "last_ts_now": rows[-1]["timestamp"],
            "source": kwargs.get("source_name"),
        }

    monkeypatch.setattr(worker, "ingest_records", fake_ingest)

    config = worker.WorkerConfig(
        symbols=["USDJPY"],
        modes=["conservative"],
        tf="5m",
        interval=0.0,
        lookback_minutes=5,
        freshness_threshold=30,
        offer_side="bid",
        snapshot_path=tmp_path / "ops/runtime_snapshot.json",
        raw_root=tmp_path / "raw",
        validated_root=tmp_path / "validated",
        features_root=tmp_path / "features",
        shutdown_file=None,
        max_iterations=None,
        or_n=6,
    )

    now = datetime(2024, 1, 1, 0, 30)
    result = worker._ingest_symbol("USDJPY", config, now=now)

    assert result is not None
    assert result.get("source") == "yfinance"
    expected_start = ingest_providers.compute_yfinance_fallback_start(
        last_ts=last_processed,
        lookback_minutes=config.lookback_minutes,
        now=now,
    )
    assert fallback_calls["start"] == expected_start
    assert ingests and ingests[0]["source_name"] == "yfinance"


def test_ingest_symbol_yfinance_fallback_excludes_offer_side(monkeypatch, tmp_path):
    def fail_fetch(*_args, **_kwargs):
        raise ingest_providers.ProviderError("no rows returned")

    monkeypatch.setattr(worker, "_load_dukascopy_records", fail_fetch)
    fallback_rows = [
        {
            "timestamp": "2024-01-01T00:10:00",
            "symbol": "USDJPY",
            "tf": "5m",
            "o": 151.0,
            "h": 151.2,
            "l": 150.8,
            "c": 151.1,
            "v": 700.0,
            "spread": 0.1,
        }
    ]
    monkeypatch.setattr(worker, "_load_yfinance_records", lambda *a, **k: list(fallback_rows))
    monkeypatch.setattr(worker, "get_last_processed_ts", lambda *a, **k: None)

    ingests = []

    def fake_ingest(records, *, symbol, tf, snapshot_path, raw_path, validated_path, features_path, or_n, source_name):
        records_list = list(records)
        ingests.append({
            "symbol": symbol,
            "tf": tf,
            "records": records_list,
            "source_name": source_name,
        })
        return {
            "rows_validated": len(records_list),
            "anomalies_logged": 0,
            "last_ts_now": "2024-01-01T00:10:00",
            "source": source_name,
        }

    monkeypatch.setattr(worker, "ingest_records", fake_ingest)

    config = worker.WorkerConfig(
        symbols=["USDJPY"],
        modes=["conservative"],
        tf="5m",
        interval=0.0,
        lookback_minutes=5,
        freshness_threshold=90,
        offer_side="bid",
        snapshot_path=tmp_path / "ops/runtime_snapshot.json",
        raw_root=tmp_path / "raw",
        validated_root=tmp_path / "validated",
        features_root=tmp_path / "features",
        shutdown_file=None,
        max_iterations=None,
        or_n=6,
    )

    result = worker._ingest_symbol("USDJPY", config, now=datetime(2024, 1, 1, 0, 15, 0))

    assert result is not None
    assert result.get("source") == "yfinance"
    assert "dukascopy_offer_side" not in result
    assert ingests and ingests[0]["source_name"] == "yfinance"


def test_ingest_symbol_dukascopy_attaches_offer_side(monkeypatch, tmp_path):
    rows = [
        {
            "timestamp": "2024-01-01T00:10:00",
            "symbol": "USDJPY",
            "tf": "5m",
            "o": 150.0,
            "h": 150.2,
            "l": 149.9,
            "c": 150.1,
            "v": 1200.0,
            "spread": 0.1,
        },
        {
            "timestamp": "2024-01-01T00:15:00",
            "symbol": "USDJPY",
            "tf": "5m",
            "o": 150.1,
            "h": 150.3,
            "l": 149.8,
            "c": 150.0,
            "v": 900.0,
            "spread": 0.1,
        },
    ]

    monkeypatch.setattr(worker, "_load_dukascopy_records", lambda *a, **k: list(rows))
    monkeypatch.setattr(worker, "get_last_processed_ts", lambda *a, **k: None)

    ingests = []

    def fake_ingest(records, *, symbol, tf, snapshot_path, raw_path, validated_path, features_path, or_n, source_name):
        records_list = list(records)
        ingests.append({
            "symbol": symbol,
            "tf": tf,
            "records": records_list,
            "source_name": source_name,
        })
        return {
            "rows_validated": len(records_list),
            "anomalies_logged": 0,
            "gaps_detected": 0,
            "rows_raw": len(records_list),
            "rows_featured": len(records_list),
            "last_ts_now": rows[-1]["timestamp"],
            "source": source_name,
        }

    monkeypatch.setattr(worker, "ingest_records", fake_ingest)

    config = worker.WorkerConfig(
        symbols=["USDJPY"],
        modes=["conservative"],
        tf="5m",
        interval=0.0,
        lookback_minutes=5,
        freshness_threshold=90,
        offer_side="ask",
        snapshot_path=tmp_path / "ops/runtime_snapshot.json",
        raw_root=tmp_path / "raw",
        validated_root=tmp_path / "validated",
        features_root=tmp_path / "features",
        shutdown_file=None,
        max_iterations=None,
        or_n=6,
    )

    result = worker._ingest_symbol("USDJPY", config, now=datetime(2024, 1, 1, 0, 20, 0))

    assert result is not None
    assert result.get("source") == "dukascopy"
    assert result.get("dukascopy_offer_side") == "ask"
    assert "source_name" not in result
    assert ingests and ingests[0]["source_name"] == "dukascopy"


def test_run_update_state_passes_lowercase_mode(monkeypatch, tmp_path):
    calls = []

    def fake_main(args):
        calls.append(args)
        return 0

    monkeypatch.setattr("scripts.update_state.main", fake_main)

    bars_path = tmp_path / "bars.csv"
    worker._run_update_state("USDJPY", "conservative", bars_path=bars_path)

    assert calls == [
        [
            "--bars",
            str(bars_path),
            "--symbol",
            "USDJPY",
            "--mode",
            "conservative",
        ]
    ]


def test_live_worker_uses_shared_timestamp_parser():
    from scripts import _time_utils

    parser = worker._parse_timestamp

    assert parser is _time_utils.parse_naive_utc
    assert parser("2024-01-01T00:00:00Z") == datetime(2024, 1, 1, 0, 0)
    assert parser("2024-01-01 00:00:00", fallback_formats=("%Y-%m-%d %H:%M:%S",)) == datetime(
        2024, 1, 1, 0, 0
    )
    assert parser("") is None
    assert parser("invalid") is None

