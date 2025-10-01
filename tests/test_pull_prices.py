import csv
import json
import subprocess
import sys
from pathlib import Path

from scripts.pull_prices import ingest_records


ROOT = Path(__file__).resolve().parents[1]


SOURCE_CSV = """timestamp,symbol,tf,o,h,l,c,v,spread
2024-01-01T00:00:00Z,USDJPY,5m,150.00,150.10,149.90,150.02,120,0.02
2024-01-01T00:05:00+00:00,USDJPY,5m,150.02,150.12,149.92,150.04,118,0.02
2024-01-01T00:10:00,USDJPY,5m,150.04,150.14,149.94,150.06,116,0.02
2024-01-01T00:15:00,USDJPY,5m,150.06,150.16,149.96,150.08,114,0.02
2024-01-01T00:20:00,USDJPY,5m,150.08,150.18,149.98,150.10,112,0.02
2024-01-01 00:25:00,USDJPY,5m,150.10,150.20,150.00,150.12,110,0.02
2024-01-01 00:30:00,USDJPY,5m,150.12,150.22,150.02,150.14,108,0.02
2024-01-01 00:35:00,USDJPY,5m,150.14,150.24,150.04,150.16,106,0.02
"""


def _run_pull_prices(tmp_path: Path) -> dict:
    source_csv = tmp_path / "source.csv"
    source_csv.write_text(SOURCE_CSV)
    snapshot_path = tmp_path / "snapshot.json"
    cmd = [
        sys.executable,
        str(ROOT / "scripts/pull_prices.py"),
        "--source",
        str(source_csv),
        "--symbol",
        "USDJPY",
        "--tf",
        "5m",
        "--snapshot",
        str(snapshot_path),
    ]
    proc = subprocess.run(cmd, cwd=tmp_path, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout.strip())
    return payload


def test_pull_prices_pipeline(tmp_path):
    payload = _run_pull_prices(tmp_path)
    assert payload["rows_raw"] == 8
    assert payload["rows_validated"] == 8
    assert payload["rows_featured"] == 8
    assert payload["gaps_detected"] == 0
    assert payload["last_ts_now"].endswith("00:35:00")

    raw_path = tmp_path / "raw" / "USDJPY" / "5m.csv"
    validated_path = tmp_path / "validated" / "USDJPY" / "5m.csv"
    features_path = tmp_path / "features" / "USDJPY" / "5m.csv"
    snapshot_path = tmp_path / "snapshot.json"
    anomalies_path = tmp_path / "ops" / "logs" / "ingest_anomalies.jsonl"

    assert raw_path.exists()
    assert validated_path.exists()
    assert features_path.exists()
    assert snapshot_path.exists()
    assert not anomalies_path.exists()

    with raw_path.open(newline="", encoding="utf-8") as f:
        raw_rows = list(csv.DictReader(f))
    assert len(raw_rows) == 8
    assert raw_rows[0]["timestamp"].endswith("00:00:00Z")

    with validated_path.open(newline="", encoding="utf-8") as f:
        validated_rows = list(csv.DictReader(f))
    assert len(validated_rows) == 8
    assert validated_rows[-1]["timestamp"].endswith("00:35:00")

    with features_path.open(newline="", encoding="utf-8") as f:
        feature_rows = list(csv.DictReader(f))
    assert len(feature_rows) == 8
    last_feature = feature_rows[-1]
    assert last_feature["or_high"] != ""
    assert last_feature["or_low"] != ""

    snapshot_data = json.loads(snapshot_path.read_text())
    assert snapshot_data["ingest"]["USDJPY_5m"].endswith("00:35:00")

    payload_second = _run_pull_prices(tmp_path)
    assert payload_second["rows_raw"] == 0
    assert payload_second["rows_validated"] == 0
    assert payload_second["rows_featured"] == 0

    with features_path.open(newline="", encoding="utf-8") as f:
        feature_rows_second = list(csv.DictReader(f))
    assert len(feature_rows_second) == 8


def test_ingest_records_inline(tmp_path):
    snapshot_path = tmp_path / "snapshot.json"
    raw_path = tmp_path / "raw" / "USDJPY" / "5m.csv"
    validated_path = tmp_path / "validated" / "USDJPY" / "5m.csv"
    features_path = tmp_path / "features" / "USDJPY" / "5m.csv"

    rows = [
        {
            "timestamp": "2024-01-02T00:00:00Z",
            "symbol": "USDJPY",
            "tf": "5m",
            "o": 150.0,
            "h": 150.1,
            "l": 149.9,
            "c": 150.02,
            "v": 120,
            "spread": 0.02,
        },
        {
            "timestamp": "2024-01-02T00:05:00Z",
            "symbol": "USDJPY",
            "tf": "5m",
            "o": 150.02,
            "h": 150.12,
            "l": 149.92,
            "c": 150.04,
            "v": 118,
            "spread": 0.02,
        },
    ]

    result = ingest_records(
        rows,
        symbol="USDJPY",
        tf="5m",
        snapshot_path=snapshot_path,
        raw_path=raw_path,
        validated_path=validated_path,
        features_path=features_path,
    )

    assert result["rows_validated"] == 2
    assert result["last_ts_now"].endswith("00:05:00")

    # Second run should be idempotent
    result_second = ingest_records(
        rows,
        symbol="USDJPY",
        tf="5m",
        snapshot_path=snapshot_path,
        raw_path=raw_path,
        validated_path=validated_path,
        features_path=features_path,
    )
    assert result_second["rows_validated"] == 0


def test_non_monotonic_rows_skip_raw(tmp_path, monkeypatch):
    snapshot_path = tmp_path / "snapshot.json"
    raw_path = tmp_path / "raw" / "USDJPY" / "5m.csv"
    validated_path = tmp_path / "validated" / "USDJPY" / "5m.csv"
    features_path = tmp_path / "features" / "USDJPY" / "5m.csv"

    from scripts import pull_prices

    anomaly_log = tmp_path / "ops" / "logs" / "ingest_anomalies.jsonl"
    monkeypatch.setattr(pull_prices, "ANOMALY_LOG", anomaly_log)

    rows = [
        {
            "timestamp": "2024-02-01T00:00:00Z",
            "symbol": "USDJPY",
            "tf": "5m",
            "o": 150.0,
            "h": 150.1,
            "l": 149.9,
            "c": 150.02,
            "v": 100,
            "spread": 0.02,
        },
        {
            "timestamp": "2024-02-01T00:05:00Z",
            "symbol": "USDJPY",
            "tf": "5m",
            "o": 150.02,
            "h": 150.12,
            "l": 149.92,
            "c": 150.04,
            "v": 105,
            "spread": 0.02,
        },
        {
            "timestamp": "2024-02-01T00:05:00Z",
            "symbol": "USDJPY",
            "tf": "5m",
            "o": 150.02,
            "h": 150.18,
            "l": 149.90,
            "c": 150.06,
            "v": 110,
            "spread": 0.02,
        },
    ]

    result = ingest_records(
        rows,
        symbol="USDJPY",
        tf="5m",
        snapshot_path=snapshot_path,
        raw_path=raw_path,
        validated_path=validated_path,
        features_path=features_path,
    )

    assert result["rows_raw"] == 2
    assert result["rows_validated"] == 2
    assert result["anomalies_logged"] == 1

    with raw_path.open(newline="", encoding="utf-8") as f:
        raw_rows = list(csv.DictReader(f))
    assert len(raw_rows) == 2

    with anomaly_log.open(encoding="utf-8") as f:
        entries = [json.loads(line) for line in f]
    assert entries[0]["type"] == "non_monotonic"
