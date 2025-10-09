#!/usr/bin/env python3
"""Quick data quality audit for 5m OHLC CSV files."""
from __future__ import annotations
import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Set

REQUIRED_COLS = ["timestamp", "symbol", "tf", "o", "h", "l", "c", "spread"]


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Audit OHLC 5m CSV for basic quality checks")
    p.add_argument("--csv", required=True,
                   help="Input CSV path (timestamp,symbol,tf,o,h,l,c,v,spread)")
    p.add_argument("--symbol", default=None, help="Optional symbol filter")
    p.add_argument("--out-json", default=None,
                   help="Optional JSON output path for structured summary")
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
    monotonic_errors = 0
    tf_counter = Counter()
    symbol_counter = Counter()
    last_ts: datetime | None = None
    gaps = []
    gap_minutes: List[float] = []
    earliest_ts: datetime | None = None
    latest_ts: datetime | None = None
    total_rows = 0
    unique_ts: Set[datetime] = set()

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
            total_rows += 1
            tf_counter[tf] += 1
            symbol_counter[sym] += 1
            unique_ts.add(ts)
            if earliest_ts is None or ts < earliest_ts:
                earliest_ts = ts
            if latest_ts is None or ts > latest_ts:
                latest_ts = ts
            if last_ts and ts <= last_ts:
                if ts == last_ts:
                    duplicates += 1
                else:
                    issues.append(f"non-monotonic timestamp: {last_ts.isoformat()} -> {ts.isoformat()}")
                    monotonic_errors += 1
            if last_ts:
                diff = ts - last_ts
                if diff > timedelta(0) and diff != timedelta(minutes=5):
                    gap_min = diff.total_seconds() / 60.0
                    gaps.append((last_ts.isoformat(), ts.isoformat(), gap_min))
                    gap_minutes.append(gap_min)
            last_ts = ts

    expected_rows = None
    coverage_ratio = None
    if earliest_ts is not None and latest_ts is not None and latest_ts >= earliest_ts:
        span_minutes = (latest_ts - earliest_ts).total_seconds() / 60.0
        expected_rows = int(span_minutes / 5) + 1
        if expected_rows > 0:
            coverage_ratio = len(unique_ts) / expected_rows

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
        "row_count": total_rows,
        "unique_timestamps": len(unique_ts),
        "start_timestamp": earliest_ts.isoformat() if earliest_ts else None,
        "end_timestamp": latest_ts.isoformat() if latest_ts else None,
        "expected_rows": expected_rows,
        "coverage_ratio": coverage_ratio,
        "gap_count": len(gaps),
        "max_gap_minutes": max(gap_minutes) if gap_minutes else 0.0,
        "monotonic_errors": monotonic_errors,
    }
    return summary


def main(argv=None):
    args = parse_args(argv)
    csv_path = Path(args.csv)
    if not csv_path.exists():
        raise SystemExit(f"CSV not found: {csv_path}")
    summary = audit(csv_path, args.symbol)
    print(summary)
    if getattr(args, "out_json", None):
        out_path = Path(args.out_json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
