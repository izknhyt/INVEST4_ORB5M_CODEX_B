#!/usr/bin/env python3
"""On-demand price ingestion pipeline for 5m bars.

The workflow mirrors the design backlog requirement:

- Append unseen rows from a historical CSV (or API export) into tiered storage
  `raw/<symbol>/<tf>.csv`, `validated/<symbol>/<tf>.csv`, and
  `features/<symbol>/<tf>.csv`.
- Track the latest successfully processed timestamp in
  `ops/runtime_snapshot.json` under `ingest`.
- Record anomalies (parse errors, gaps, duplicates) in
  `ops/logs/ingest_anomalies.jsonl` so the run can be replayed or inspected.

The script remains idempotent: repeated invocations only touch rows newer than
the last processed timestamp. Use `--dry-run` to preview without writing.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Deque, Dict, Iterable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts._time_utils import utcnow_iso
from scripts._ts_utils import parse_naive_utc_timestamp
from core.feature_store import adx as calc_adx
from core.feature_store import atr as calc_atr
from core.feature_store import opening_range, realized_vol


SNAPSHOT_PATH = Path("ops/runtime_snapshot.json")
DEFAULT_SOURCE = Path("data/usdjpy_5m_2018-2024_utc.csv")
RAW_ROOT = Path("raw")
VALIDATED_ROOT = Path("validated")
FEATURES_ROOT = Path("features")
ANOMALY_LOG = Path("ops/logs/ingest_anomalies.jsonl")

RAW_HEADER = ["timestamp", "symbol", "tf", "o", "h", "l", "c", "v", "spread"]
VALIDATED_HEADER = RAW_HEADER.copy()
FEATURE_HEADER = RAW_HEADER + ["atr14", "adx14", "or_high", "or_low", "rv12"]


def _utcnow_iso() -> str:
    """Return the current UTC time in ISO format (seconds precision)."""

    return utcnow_iso(dt_cls=datetime)


def _load_snapshot(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with path.open() as f:
            return json.load(f)
    except Exception:
        return {}


def _save_snapshot(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _parse_ts(value: str) -> datetime:
    return parse_naive_utc_timestamp(
        value,
        fallback_formats=("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"),
    )


def record_ingest_metadata(
    symbol: str,
    tf: str,
    metadata: Dict[str, object],
    *,
    snapshot_path: Path = SNAPSHOT_PATH,
) -> None:
    """Persist supplementary ingestion metadata to the runtime snapshot."""

    snapshot_path = Path(snapshot_path)
    snapshot = _load_snapshot(snapshot_path)
    key = f"{symbol}_{tf}"
    ingest_meta = snapshot.setdefault("ingest_meta", {})
    payload = dict(metadata)
    payload["updated_at"] = _utcnow_iso()
    ingest_meta[key] = payload
    _save_snapshot(snapshot_path, snapshot)


def _last_ts_from_snapshot(snapshot: dict, key: str) -> Optional[datetime]:
    section = snapshot.get("ingest", {})
    ts_str = section.get(key)
    if not ts_str:
        return None
    try:
        return datetime.fromisoformat(ts_str)
    except ValueError:
        return None


def _update_snapshot(snapshot: dict, key: str, value: datetime) -> dict:
    ingest = snapshot.setdefault("ingest", {})
    ingest[key] = value.isoformat()
    return snapshot


def _infer_last_ts_from_csv(path: Path) -> Optional[datetime]:
    if not path.exists():
        return None
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            last_ts = None
            for row in reader:
                ts_raw = row.get("timestamp")
                if not ts_raw:
                    continue
                try:
                    last_ts = _parse_ts(ts_raw)
                except Exception:
                    continue
            return last_ts
    except Exception:
        return None


def _append_csv(path: Path, header: List[str], rows: Iterable[Iterable[object]], *, dry_run: bool) -> int:
    rows_list = list(rows)
    if dry_run or not rows_list:
        return len(rows_list)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(header)
        writer.writerows(rows_list)
    return len(rows_list)


def _log_anomalies(entries: Iterable[Dict[str, object]], *, dry_run: bool) -> int:
    entries_list = list(entries)
    if dry_run or not entries_list:
        return len(entries_list)
    ANOMALY_LOG.parent.mkdir(parents=True, exist_ok=True)
    with ANOMALY_LOG.open("a", encoding="utf-8") as f:
        for entry in entries_list:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return len(entries_list)


def _load_recent_validated(path: Path, limit: int = 400) -> List[Dict[str, object]]:
    if not path.exists():
        return []
    buf: Deque[Dict[str, object]] = deque(maxlen=limit)
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                ts = _parse_ts(row["timestamp"])
                buf.append({
                    "dt": ts,
                    "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%S"),
                    "symbol": row.get("symbol", ""),
                    "tf": row.get("tf", ""),
                    "o": float(row["o"]),
                    "h": float(row["h"]),
                    "l": float(row["l"]),
                    "c": float(row["c"]),
                    "v": float(row.get("v", 0.0) or 0.0),
                    "spread": float(row.get("spread", 0.0) or 0.0),
                })
            except Exception:
                continue
    return list(buf)


class FeatureContext:
    """Maintain rolling context so feature columns stay consistent run-to-run."""

    def __init__(self, *, or_n: int = 6):
        self.window: Deque[Dict[str, float]] = deque(maxlen=400)
        self.or_n = max(1, or_n)
        self.session_bars: List[Dict[str, float]] = []
        self._session_key: Optional[str] = None

    @staticmethod
    def _session_id(dt: datetime) -> str:
        return dt.strftime("%Y-%m-%d")

    def bootstrap(self, rows: Iterable[Dict[str, object]]) -> None:
        for row in rows:
            self._update_context(row["dt"], row, compute=False)

    def compute(self, dt: datetime, row: Dict[str, object]) -> Tuple[float, float, float, float, float]:
        return self._update_context(dt, row, compute=True)

    def _update_context(self, dt: datetime, row: Dict[str, object], *, compute: bool) -> Tuple[float, float, float, float, float]:
        session_id = self._session_id(dt)
        if self._session_key != session_id:
            self._session_key = session_id
            self.session_bars = []

        bar_core = {k: float(row[k]) for k in ("o", "h", "l", "c")}
        self.window.append(bar_core)
        self.session_bars.append(bar_core)

        if not compute:
            return (float("nan"),) * 5

        atr14 = float("nan")
        adx14 = float("nan")
        if len(self.window) >= 15:
            slice_window = list(self.window)[-15:]
            try:
                atr14 = calc_atr(slice_window)
            except Exception:
                atr14 = float("nan")
            try:
                adx14 = calc_adx(slice_window)
            except Exception:
                adx14 = float("nan")

        or_high, or_low = opening_range(self.session_bars, n=self.or_n)
        try:
            rv12 = realized_vol(list(self.window), n=12)
        except Exception:
            rv12 = float("nan")

        return atr14, adx14, or_high, or_low, rv12


def _format_ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _format_float(val: float) -> str:
    if val != val or val is None:  # NaN handling becomes blank
        return ""
    text = f"{val:.10f}".rstrip("0").rstrip(".")
    return text or "0"


def get_last_processed_ts(
    symbol: str,
    tf: str,
    *,
    snapshot_path: Path = SNAPSHOT_PATH,
    validated_path: Optional[Path] = None,
) -> Optional[datetime]:
    """Return the last ingested timestamp, using snapshot first then validated CSV."""

    snapshot = _load_snapshot(snapshot_path)
    key = f"{symbol}_{tf}"
    last_ts = _last_ts_from_snapshot(snapshot, key)
    if last_ts is not None:
        return last_ts

    validated_path = validated_path or VALIDATED_ROOT / symbol / f"{tf}.csv"
    return _infer_last_ts_from_csv(validated_path)


def ingest_records(
    records: Iterable[Dict[str, object]],
    *,
    symbol: str,
    tf: str,
    snapshot_path: Path = SNAPSHOT_PATH,
    raw_path: Optional[Path] = None,
    validated_path: Optional[Path] = None,
    features_path: Optional[Path] = None,
    or_n: int = 6,
    dry_run: bool = False,
    source_name: Optional[str] = None,
) -> Dict[str, object]:
    """Ingest pre-normalized bar records into raw/validated/feature storage."""

    symbol = symbol.upper()
    tf = tf

    raw_path = raw_path or RAW_ROOT / symbol / f"{tf}.csv"
    validated_path = validated_path or VALIDATED_ROOT / symbol / f"{tf}.csv"
    features_path = features_path or FEATURES_ROOT / symbol / f"{tf}.csv"
    snapshot_path = Path(snapshot_path)

    snapshot = _load_snapshot(snapshot_path)
    key = f"{symbol}_{tf}"
    last_ts = _last_ts_from_snapshot(snapshot, key)
    if last_ts is None:
        last_ts = _infer_last_ts_from_csv(validated_path)

    history = _load_recent_validated(validated_path)
    ctx = FeatureContext(or_n=or_n)
    ctx.bootstrap(history)
    prev_dt = history[-1]["dt"] if history else None

    raw_rows: List[List[object]] = []
    validated_rows: List[List[object]] = []
    feature_rows: List[List[object]] = []
    anomalies: List[Dict[str, object]] = []
    gaps: List[Dict[str, object]] = []

    latest_ts: Optional[datetime] = last_ts

    for row in records:
        ts_raw = str(row.get("timestamp", ""))
        try:
            ts = _parse_ts(ts_raw)
        except Exception as exc:
            anomalies.append(
                {
                    "type": "parse_error",
                    "reason": str(exc),
                    "row": row,
                }
            )
            continue

        if last_ts and ts <= last_ts:
            continue

        raw_record = [row.get(h, "") for h in RAW_HEADER]

        try:
            o = float(row.get("o", 0.0))
            h_val = float(row.get("h", 0.0))
            l = float(row.get("l", 0.0))
            c = float(row.get("c", 0.0))
            v = float(row.get("v", 0.0) or 0.0)
            spread = float(row.get("spread", 0.0) or 0.0)
        except Exception as exc:
            anomalies.append(
                {
                    "type": "numeric_error",
                    "reason": str(exc),
                    "row": row,
                }
            )
            continue

        tf_val = str(row.get("tf", "")).strip() or tf
        sym_val = str(row.get("symbol", symbol)).strip() or symbol
        if tf_val != tf:
            anomalies.append(
                {
                    "type": "tf_mismatch",
                    "expected": tf,
                    "actual": tf_val,
                    "timestamp": ts_raw,
                }
            )
            continue
        if sym_val.upper() != symbol:
            anomalies.append(
                {
                    "type": "symbol_mismatch",
                    "expected": symbol,
                    "actual": sym_val,
                    "timestamp": ts_raw,
                }
            )
            continue

        if h_val < max(o, c) or l > min(o, c) or l > h_val:
            anomalies.append(
                {
                    "type": "ohlc_invalid",
                    "timestamp": ts_raw,
                    "values": {"o": o, "h": h_val, "l": l, "c": c},
                }
            )
            continue

        if prev_dt and ts <= prev_dt:
            info = {
                "type": "non_monotonic",
                "prev_ts": _format_ts(prev_dt),
                "current_ts": _format_ts(ts),
            }
            anomalies.append(info)
            continue

        if prev_dt and ts - prev_dt > timedelta(minutes=5):
            gap_entry = {
                "type": "gap",
                "start_ts": _format_ts(prev_dt),
                "end_ts": _format_ts(ts),
                "minutes": (ts - prev_dt).total_seconds() / 60.0,
            }
            gaps.append(gap_entry)
            anomalies.append(gap_entry)

        prev_dt = ts
        latest_ts = ts if latest_ts is None or ts > latest_ts else latest_ts

        raw_rows.append(raw_record)

        ts_str = _format_ts(ts)
        validated_rows.append(
            [
                ts_str,
                symbol,
                tf,
                o,
                h_val,
                l,
                c,
                v,
                spread,
            ]
        )

        feature_vals = ctx.compute(
            ts,
            {
                "o": o,
                "h": h_val,
                "l": l,
                "c": c,
            },
        )

        feature_rows.append(
            [
                ts_str,
                symbol,
                tf,
                o,
                h_val,
                l,
                c,
                v,
                spread,
                _format_float(feature_vals[0]),
                _format_float(feature_vals[1]),
                _format_float(feature_vals[2]),
                _format_float(feature_vals[3]),
                _format_float(feature_vals[4]),
            ]
        )

    raw_rows_count = _append_csv(raw_path, RAW_HEADER, raw_rows, dry_run=dry_run)
    validated_rows_count = _append_csv(
        validated_path, VALIDATED_HEADER, validated_rows, dry_run=dry_run
    )
    feature_rows_count = _append_csv(
        features_path, FEATURE_HEADER, feature_rows, dry_run=dry_run
    )
    anomalies_logged = _log_anomalies(anomalies, dry_run=dry_run)

    result = {
        "source": source_name or "inline",
        "raw_path": str(raw_path),
        "validated_path": str(validated_path),
        "features_path": str(features_path),
        "rows_raw": raw_rows_count,
        "rows_validated": validated_rows_count,
        "rows_featured": feature_rows_count,
        "anomalies_logged": anomalies_logged,
        "gaps_detected": len(gaps),
        "last_ts_prev": last_ts.isoformat() if last_ts else None,
        "last_ts_now": latest_ts.isoformat() if latest_ts else None,
    }

    if dry_run or raw_rows_count == 0 or latest_ts is None:
        return result

    if last_ts is None or latest_ts > last_ts:
        updated = _update_snapshot(snapshot, key, latest_ts)
        _save_snapshot(snapshot_path, updated)

    return result


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="On-demand ingestion for 5m bars")
    parser.add_argument("--source", default=str(DEFAULT_SOURCE), help="Source CSV path")
    parser.add_argument("--symbol", default="USDJPY", help="Symbol key (used for snapshot)")
    parser.add_argument("--tf", default="5m", help="Timeframe key (default 5m)")
    parser.add_argument("--snapshot", default=str(SNAPSHOT_PATH), help="Runtime snapshot JSON path")
    parser.add_argument("--or-n", type=int, default=6, help="Opening range length for feature calc")
    parser.add_argument("--dry-run", action="store_true", help="Scan without writing output or snapshot")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    source = Path(args.source)
    if not source.exists():
        print(json.dumps({"error": "source_not_found", "path": str(source)}))
        return 1

    symbol = args.symbol.upper()
    tf = args.tf

    raw_path = RAW_ROOT / symbol / f"{tf}.csv"
    validated_path = VALIDATED_ROOT / symbol / f"{tf}.csv"
    features_path = FEATURES_ROOT / symbol / f"{tf}.csv"

    with source.open(newline="", encoding="utf-8") as src_f:
        reader = csv.DictReader(src_f)
        result = ingest_records(
            reader,
            symbol=symbol,
            tf=tf,
            snapshot_path=Path(args.snapshot),
            raw_path=raw_path,
            validated_path=validated_path,
            features_path=features_path,
            or_n=args.or_n,
            dry_run=args.dry_run,
            source_name=str(source),
        )

    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
