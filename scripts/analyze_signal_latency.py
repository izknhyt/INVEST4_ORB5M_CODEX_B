#!/usr/bin/env python3
"""Compute latency SLO stats from ops/signal_latency.csv."""
from __future__ import annotations
import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict

from scripts._ts_utils import _normalize_iso_string


def parse_iso(ts: str) -> datetime:
    text = ts.strip()
    normalized = _normalize_iso_string(text)
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        # allow space separator
        normalized = _normalize_iso_string(text.replace(" ", "T"))
        return datetime.fromisoformat(normalized)


def load_latencies(path: Path) -> List[Dict[str, object]]:
    records: List[Dict[str, object]] = []
    if not path.exists():
        return records
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                emit = parse_iso(row["ts_emit"])
                ack = parse_iso(row["ts_ack"])
                latency = (ack - emit).total_seconds()
            except Exception:
                continue
            records.append({
                "signal_id": row.get("signal_id"),
                "status": row.get("status", ""),
                "latency": latency,
                "detail": row.get("detail", ""),
            })
    return records


def percentile(values: List[float], pct: float) -> float:
    if not values:
        return 0.0
    values_sorted = sorted(values)
    k = min(len(values_sorted) - 1, max(0, int(round((pct / 100.0) * (len(values_sorted) - 1)))))
    return values_sorted[k]


def analyze(records: List[Dict[str, object]], slo_threshold: float) -> Dict[str, object]:
    total = len(records)
    failures = sum(1 for r in records if r.get("status") != "success")
    latencies = [float(r["latency"]) for r in records if isinstance(r.get("latency"), (int, float))]
    over_slo = sum(1 for r in latencies if r > slo_threshold)

    summary = {
        "total": total,
        "failures": failures,
        "failure_rate": (failures / total) if total else 0.0,
        "avg_latency": (sum(latencies) / len(latencies)) if latencies else 0.0,
        "p50_latency": percentile(latencies, 50) if latencies else 0.0,
        "p95_latency": percentile(latencies, 95) if latencies else 0.0,
        "p99_latency": percentile(latencies, 99) if latencies else 0.0,
        "slo_threshold": slo_threshold,
        "slo_breach_ratio": (over_slo / len(latencies)) if latencies else 0.0,
    }
    return summary


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Analyze signal latency log")
    p.add_argument("--input", default="ops/signal_latency.csv", help="Path to latency CSV")
    p.add_argument("--slo-threshold", type=float, default=5.0, help="SLO閾値 (秒) (p95<=threshold)\n")
    p.add_argument("--json-out", default=None, help="結果をJSONで出力するパス")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    path = Path(args.input)
    records = load_latencies(path)
    summary = analyze(records, args.slo_threshold)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if summary["p95_latency"] > args.slo_threshold or summary["failure_rate"] > 0.01:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
