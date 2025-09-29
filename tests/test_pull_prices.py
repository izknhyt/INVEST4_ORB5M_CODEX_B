import csv
import json
import subprocess
import sys
from pathlib import Path


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


GAP_SOURCE_CSV = """timestamp,symbol,tf,o,h,l,c,v,spread
2024-01-01T00:00:00Z,USDJPY,5m,150.00,150.10,149.90,150.02,120,0.02
2024-01-01T00:15:00Z,USDJPY,5m,150.02,150.12,149.92,150.04,118,0.02
2024-01-01T00:20:00Z,USDJPY,5m,150.04,150.14,149.94,150.06,116,0.02
"""


MISMATCH_SOURCE_CSV = """timestamp,symbol,tf,o,h,l,c,v,spread
2024-01-01T00:40:00Z,USDJPY,1m,150.20,150.30,150.10,150.22,100,0.02
2024-01-01T00:45:00Z,EURUSD,5m,150.22,150.32,150.12,150.24,98,0.02
"""


def _run_pull_prices(
    tmp_path: Path,
    *,
    csv_text: str = SOURCE_CSV,
    extra_args: list[str] | None = None,
) -> dict:
    source_csv = tmp_path / "source.csv"
    source_csv.write_text(csv_text)
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
    if extra_args:
        cmd.extend(extra_args)
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


def test_pull_prices_gap_detection(tmp_path):
    payload = _run_pull_prices(tmp_path, csv_text=GAP_SOURCE_CSV)
    assert payload["rows_raw"] == 3
    assert payload["rows_validated"] == 3
    assert payload["rows_featured"] == 3
    assert payload["gaps_detected"] == 1
    assert payload["anomalies_logged"] == 1

    anomalies_path = tmp_path / "ops" / "logs" / "ingest_anomalies.jsonl"
    assert anomalies_path.exists()

    records = [json.loads(line) for line in anomalies_path.read_text().splitlines() if line]
    assert len(records) == 1
    gap_entry = records[0]
    assert gap_entry["type"] == "gap"
    assert gap_entry["minutes"] == 15.0


def test_pull_prices_mismatched_rows_stay_in_raw(tmp_path):
    base_payload = _run_pull_prices(tmp_path)
    assert base_payload["rows_validated"] == 8

    raw_path = tmp_path / "raw" / "USDJPY" / "5m.csv"
    validated_path = tmp_path / "validated" / "USDJPY" / "5m.csv"
    features_path = tmp_path / "features" / "USDJPY" / "5m.csv"
    anomalies_path = tmp_path / "ops" / "logs" / "ingest_anomalies.jsonl"

    assert raw_path.exists()
    assert validated_path.exists()
    assert features_path.exists()
    assert not anomalies_path.exists()

    payload = _run_pull_prices(tmp_path, csv_text=MISMATCH_SOURCE_CSV)
    assert payload["rows_raw"] == 2
    assert payload["rows_validated"] == 0
    assert payload["rows_featured"] == 0
    assert payload["anomalies_logged"] == 2
    assert payload["gaps_detected"] == 0

    with raw_path.open(newline="", encoding="utf-8") as f:
        raw_rows = list(csv.DictReader(f))
    assert len(raw_rows) == 10
    assert raw_rows[-2]["tf"] == "1m"
    assert raw_rows[-1]["symbol"] == "EURUSD"

    with validated_path.open(newline="", encoding="utf-8") as f:
        validated_rows = list(csv.DictReader(f))
    assert len(validated_rows) == 8

    with features_path.open(newline="", encoding="utf-8") as f:
        feature_rows = list(csv.DictReader(f))
    assert len(feature_rows) == 8

    records = [json.loads(line) for line in anomalies_path.read_text().splitlines() if line]
    types = {entry["type"] for entry in records}
    assert {"tf_mismatch", "symbol_mismatch"}.issubset(types)


def test_pull_prices_dry_run_reports_counts_without_files(tmp_path):
    payload = _run_pull_prices(tmp_path, extra_args=["--dry-run"])
    assert payload["rows_raw"] == 8
    assert payload["rows_validated"] == 8
    assert payload["rows_featured"] == 8
    assert payload["gaps_detected"] == 0
    assert payload["anomalies_logged"] == 0

    raw_path = tmp_path / "raw" / "USDJPY" / "5m.csv"
    validated_path = tmp_path / "validated" / "USDJPY" / "5m.csv"
    features_path = tmp_path / "features" / "USDJPY" / "5m.csv"
    snapshot_path = tmp_path / "snapshot.json"
    anomalies_path = tmp_path / "ops" / "logs" / "ingest_anomalies.jsonl"

    assert not raw_path.exists()
    assert not validated_path.exists()
    assert not features_path.exists()
    assert not snapshot_path.exists()
    assert not anomalies_path.exists()

