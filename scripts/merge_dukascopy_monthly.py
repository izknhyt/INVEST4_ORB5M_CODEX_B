#!/usr/bin/env python3
"""Merge monthly Dukascopy CSV exports into a single normalized file."""
from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts._ts_utils import parse_naive_utc_timestamp


HEADER = ["timestamp", "symbol", "tf", "o", "h", "l", "c", "v", "spread"]


@dataclass
class MergeStats:
    files_processed: int = 0
    rows_read: int = 0
    rows_merged: int = 0
    duplicates_skipped: int = 0


def _normalize_row(row: Dict[str, str], symbol: str, tf: str, spread_default: float) -> Dict[str, str]:
    symbol_norm = (row.get("symbol") or symbol).strip().upper()
    tf_norm = (row.get("tf") or tf).strip()

    def _pick(*keys: str) -> str:
        for key in keys:
            val = row.get(key)
            if val not in (None, ""):
                return str(val)
        return ""

    spread_val = _pick("spread")
    if not spread_val:
        spread_val = str(spread_default)

    return {
        "symbol": symbol_norm,
        "tf": tf_norm,
        "o": _pick("o", "open", "bid_open", "ask_open"),
        "h": _pick("h", "high", "bid_high", "ask_high"),
        "l": _pick("l", "low", "bid_low", "ask_low"),
        "c": _pick("c", "close", "bid_close", "ask_close"),
        "v": _pick("v", "volume"),
        "spread": spread_val,
    }


def merge_files(
    paths: Iterable[Path],
    *,
    symbol: str,
    tf: str,
    spread_default: float,
) -> tuple[List[Dict[str, str]], MergeStats]:
    rows: Dict[str, Dict[str, str]] = {}
    stats = MergeStats()

    for path in sorted(paths):
        stats.files_processed += 1
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                stats.rows_read += 1
                ts_raw = (row.get("timestamp") or "").strip()
                if not ts_raw:
                    continue
                try:
                    dt = parse_naive_utc_timestamp(ts_raw)
                except ValueError:
                    continue
                ts_norm = dt.strftime("%Y-%m-%dT%H:%M:%S")

                normalized = _normalize_row(row, symbol, tf, spread_default)
                normalized["timestamp"] = ts_norm

                if ts_norm in rows:
                    stats.duplicates_skipped += 1
                rows[ts_norm] = normalized

    ordered_keys = sorted(rows.keys())
    merged = [rows[key] for key in ordered_keys]
    stats.rows_merged = len(merged)
    return merged, stats


def write_csv(path: Path, rows: List[Dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=HEADER)
        writer.writeheader()
        writer.writerows(rows)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Merge Dukascopy monthly CSV files")
    parser.add_argument(
        "--pattern",
        default="USDJPY_??????_5min.csv",
        help="Glob pattern for monthly CSV files",
    )
    parser.add_argument(
        "--base-dir",
        default=".",
        help="Directory containing the monthly CSV files",
    )
    parser.add_argument(
        "--out",
        default=str(ROOT / "data/usdjpy_5m_merged.csv"),
        help="Output CSV path",
    )
    parser.add_argument("--symbol", default="USDJPY", help="Symbol to stamp in merged rows")
    parser.add_argument("--tf", default="5m", help="Timeframe label")
    parser.add_argument(
        "--spread-default",
        type=float,
        default=0.0,
        help="Default spread to use when source rows omit the column",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    base_dir = Path(args.base_dir)
    files = sorted(base_dir.glob(args.pattern))
    if not files:
        print(f"no files matched pattern: {base_dir}/{args.pattern}")
        return 1

    rows, stats = merge_files(
        files,
        symbol=args.symbol,
        tf=args.tf,
        spread_default=args.spread_default,
    )

    out_path = Path(args.out)
    write_csv(out_path, rows)

    print(
        {
            "files_processed": stats.files_processed,
            "rows_read": stats.rows_read,
            "rows_merged": stats.rows_merged,
            "duplicates_skipped": stats.duplicates_skipped,
            "out_path": str(out_path),
        }
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())
