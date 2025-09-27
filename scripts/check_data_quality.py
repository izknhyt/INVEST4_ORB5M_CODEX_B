#!/usr/bin/env python3
"""Quick data quality audit for 5m OHLC CSV files."""
from __future__ import annotations
import argparse
import csv
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List

REQUIRED_COLS = ["timestamp", "symbol", "tf", "o", "h", "l", "c", "spread"]


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Audit OHLC 5m CSV for basic quality checks")
    p.add_argument("--csv", required=True,
                   help="Input CSV path (timestamp,symbol,tf,o,h,l,c,v,spread)")
    p.add_argument("--symbol", default=None, help="Optional symbol filter")
    return p.parse_args(argv)


def parse_row(row: Dict[str, str]):
    ts = datetime.fromisoformat(row["timestamp"].replace(" ", "T"))
    tf = row.get("tf", "").strip()
    symbol = row.get("symbol")
    return ts, tf, symbol


def audit(csv_path: Path, symbol: str | None = None) -> Dict[str, object]:
    issues: List[str] = []
    missing_cols = 0
    bad_rows = 0
    duplicates = 0
    tf_counter = Counter()
    symbol_counter = Counter()
    last_ts: datetime | None = None
    gaps = []

    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if any(col not in row for col in REQUIRED_COLS):
                missing_cols += 1
                continue
            if symbol and row.get("symbol") != symbol:
                continue
            try:
                ts, tf, sym = parse_row(row)
                float(row["o"]); float(row["h"]); float(row["l"]); float(row["c"])
            except Exception:
                bad_rows += 1
                continue
            tf_counter[tf] += 1
            symbol_counter[sym] += 1
            if last_ts and ts <= last_ts:
                if ts == last_ts:
                    duplicates += 1
                else:
                    issues.append(f"non-monotonic timestamp: {last_ts.isoformat()} -> {ts.isoformat()}")
            if last_ts:
                diff = ts - last_ts
                if diff != timedelta(minutes=5):
                    gaps.append((last_ts.isoformat(), ts.isoformat(), diff.total_seconds()/60.0))
            last_ts = ts

    summary = {
        "csv": str(csv_path),
        "symbol_filter": symbol,
        "missing_cols": missing_cols,
        "bad_rows": bad_rows,
        "duplicates": duplicates,
        "tf_distribution": dict(tf_counter),
        "symbol_distribution": dict(symbol_counter),
        "gaps": gaps[:20],
        "issues": issues[:20],
    }
    return summary


def main(argv=None):
    args = parse_args(argv)
    csv_path = Path(args.csv)
    if not csv_path.exists():
        raise SystemExit(f"CSV not found: {csv_path}")
    summary = audit(csv_path, args.symbol)
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
