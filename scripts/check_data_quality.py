#!/usr/bin/env python3
"""Quick data quality audit for 5m OHLC CSV files."""
from __future__ import annotations
import argparse
import csv
import json
from collections import Counter
import math
from datetime import datetime, timedelta, timezone
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
    p.add_argument("--out-gap-csv", default=None,
                   help="Optional CSV output path containing the complete gap inventory")
    p.add_argument("--max-gap-report", type=int, default=20,
                   help="Maximum number of gaps retained in the summary payload (default: 20)")
    return p.parse_args(argv)


def parse_row(row: Dict[str, str]):
    raw_ts = row["timestamp"].strip().replace(" ", "T")
    if raw_ts.endswith("Z"):
        raw_ts = raw_ts[:-1]
    ts = datetime.fromisoformat(raw_ts)
    if ts.tzinfo is not None:
        ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
    tf = row.get("tf", "").strip()
    symbol = row.get("symbol")
    return ts, tf, symbol


def _audit_internal(
    csv_path: Path,
    symbol: str | None = None,
    *,
    max_gap_report: int = 20,
    capture_gap_details: bool = False,
):
    issues: List[str] = []
    missing_cols = 0
    bad_rows = 0
    duplicates = 0
    monotonic_errors = 0
    tf_counter = Counter()
    symbol_counter = Counter()
    last_ts: datetime | None = None
    gap_samples: List[Dict[str, object]] = []
    gap_minutes: List[float] = []
    total_gap_minutes = 0.0
    missing_rows_estimate = 0
    irregular_gap_count = 0
    earliest_ts: datetime | None = None
    latest_ts: datetime | None = None
    total_rows = 0
    unique_ts: Set[datetime] = set()
    full_gap_details: List[Dict[str, object]] | None = [] if capture_gap_details else None

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
                    expected_steps = diff.total_seconds() / 300.0
                    rounded_steps = round(expected_steps)
                    missing_rows = max(int(rounded_steps) - 1, 0)
                    irregular = not math.isclose(expected_steps, rounded_steps, rel_tol=1e-9, abs_tol=1e-9)
                    if irregular:
                        irregular_gap_count += 1
                        issues.append(
                            "irregular gap length: "
                            f"{last_ts.isoformat()} -> {ts.isoformat()} ({gap_min:.2f} minutes)"
                        )
                    gap_record = {
                        "start_timestamp": last_ts.isoformat(),
                        "end_timestamp": ts.isoformat(),
                        "gap_minutes": gap_min,
                        "expected_intervals": expected_steps,
                        "missing_rows_estimate": missing_rows,
                        "irregular": irregular,
                    }
                    if len(gap_samples) < max_gap_report:
                        gap_samples.append(gap_record)
                    if full_gap_details is not None:
                        full_gap_details.append(gap_record)
                    gap_minutes.append(gap_min)
                    total_gap_minutes += gap_min
                    missing_rows_estimate += missing_rows
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
        "gaps": [
            (gap["start_timestamp"], gap["end_timestamp"], gap["gap_minutes"])
            for gap in gap_samples
        ],
        "gap_details": gap_samples,
        "issues": issues[:20],
        "row_count": total_rows,
        "unique_timestamps": len(unique_ts),
        "start_timestamp": earliest_ts.isoformat() if earliest_ts else None,
        "end_timestamp": latest_ts.isoformat() if latest_ts else None,
        "expected_rows": expected_rows,
        "coverage_ratio": coverage_ratio,
        "gap_count": len(gap_minutes),
        "max_gap_minutes": max(gap_minutes) if gap_minutes else 0.0,
        "monotonic_errors": monotonic_errors,
        "missing_rows_estimate": missing_rows_estimate,
        "total_gap_minutes": total_gap_minutes,
        "average_gap_minutes": (total_gap_minutes / len(gap_minutes)) if gap_minutes else 0.0,
        "irregular_gap_count": irregular_gap_count,
    }
    return summary, full_gap_details if full_gap_details is not None else gap_samples


def audit(
    csv_path: Path,
    symbol: str | None = None,
    *,
    max_gap_report: int = 20,
) -> Dict[str, object]:
    summary, _ = _audit_internal(
        csv_path,
        symbol,
        max_gap_report=max_gap_report,
        capture_gap_details=False,
    )
    return summary


def _write_gap_csv(path: Path, gaps: List[Dict[str, object]]):
    fieldnames = [
        "start_timestamp",
        "end_timestamp",
        "gap_minutes",
        "expected_intervals",
        "missing_rows_estimate",
        "irregular",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for gap in gaps:
            writer.writerow({
                "start_timestamp": gap["start_timestamp"],
                "end_timestamp": gap["end_timestamp"],
                "gap_minutes": gap["gap_minutes"],
                "expected_intervals": gap["expected_intervals"],
                "missing_rows_estimate": gap["missing_rows_estimate"],
                "irregular": gap["irregular"],
            })


def main(argv=None):
    args = parse_args(argv)
    csv_path = Path(args.csv)
    if not csv_path.exists():
        raise SystemExit(f"CSV not found: {csv_path}")
    summary, gap_records = _audit_internal(
        csv_path,
        args.symbol,
        max_gap_report=max(1, args.max_gap_report),
        capture_gap_details=bool(args.out_gap_csv),
    )
    print(summary)
    if getattr(args, "out_json", None):
        out_path = Path(args.out_json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
    if getattr(args, "out_gap_csv", None):
        out_gap_path = Path(args.out_gap_csv)
        _write_gap_csv(out_gap_path, gap_records)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
