import csv
from pathlib import Path
from typing import List

import pytest

from scripts import live_ingest_worker as worker


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

    def fake_dukascopy(symbol, tf, start, end):
        idx = min(len(duk_calls), len(records_seq) - 1)
        duk_calls.append((symbol, start, end))
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


def test_live_worker_fallback_to_yfinance(monkeypatch, tmp_path):
    monkeypatch.setattr(worker, "_load_dukascopy_records", lambda *a, **k: [])

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
    assert updates == [("USDJPY", "CONSERVATIVE", validated_path)]
