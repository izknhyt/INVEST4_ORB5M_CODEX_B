#!/usr/bin/env python3
"""Compute latency SLO stats from ops/signal_latency.csv."""
from __future__ import annotations
import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, cast


def parse_iso(ts: str) -> datetime:
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        # allow space separator
        return datetime.fromisoformat(ts.replace(" ", "T"))


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


def analyze(
    records: List[Dict[str, object]],
    latency_threshold: float,
    failure_threshold: float,
) -> Dict[str, object]:
    total = len(records)
    failures = sum(1 for r in records if r.get("status") != "success")
    latencies = [float(r["latency"]) for r in records if isinstance(r.get("latency"), (int, float))]
    latency_count = len(latencies)
    over_slo = sum(1 for r in latencies if r > latency_threshold)

    failure_rate = (failures / total) if total else 0.0
    avg_latency = (sum(latencies) / latency_count) if latencies else 0.0
    p50_latency = percentile(latencies, 50) if latencies else 0.0
    p95_latency = percentile(latencies, 95) if latencies else 0.0
    p99_latency = percentile(latencies, 99) if latencies else 0.0

    summary = {
        "total": total,
        "failures": failures,
        "failure_rate": failure_rate,
        "avg_latency": avg_latency,
        "p50_latency": p50_latency,
        "p95_latency": p95_latency,
        "p99_latency": p99_latency,
        "slo_threshold": latency_threshold,
        "slo_breach_ratio": (over_slo / latency_count) if latencies else 0.0,
        "latency_samples": latency_count,
    }

    thresholds = {
        "p95_latency": {
            "value": p95_latency,
            "threshold": latency_threshold,
            "breach": p95_latency > latency_threshold,
            "count_above_threshold": over_slo,
        },
        "failure_rate": {
            "value": failure_rate,
            "threshold": failure_threshold,
            "breach": failure_rate > failure_threshold,
            "count_above_threshold": failures,
        },
    }
    summary["thresholds"] = thresholds
    summary["slo_breaches"] = [name for name, info in thresholds.items() if info["breach"]]
    summary["slo_breach_count"] = len(summary["slo_breaches"])
    summary["has_breach"] = bool(summary["slo_breaches"])
    return summary


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Analyze signal latency log")
    p.add_argument("--input", default="ops/signal_latency.csv", help="Path to latency CSV")
    p.add_argument("--slo-threshold", type=float, default=5.0, help="SLO閾値 (秒) (p95<=threshold)\n")
    p.add_argument("--failure-threshold", type=float, default=0.01, help="Failure rate threshold (0-1 fraction)")
    p.add_argument("--out-json", dest="out_json", default=None, help="結果JSONの出力先")
    p.add_argument("--json-out", dest="out_json", help=argparse.SUPPRESS)
    p.add_argument("--out-csv", dest="out_csv", default=None, help="結果CSVの出力先")
    return p.parse_args(argv)


def write_summary_csv(summary: Dict[str, object], path: Path) -> None:
    fieldnames = ["metric", "value", "threshold", "breach"]
    metrics: Iterable[str] = (
        "total",
        "failures",
        "failure_rate",
        "avg_latency",
        "p50_latency",
        "p95_latency",
        "p99_latency",
        "slo_breach_ratio",
        "latency_samples",
    )
    thresholds = cast(Dict[str, Dict[str, object]], summary.get("thresholds", {}))
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for metric in metrics:
            threshold_info = thresholds.get(metric)
            writer.writerow(
                {
                    "metric": metric,
                    "value": summary.get(metric, ""),
                    "threshold": (threshold_info or {}).get("threshold", ""),
                    "breach": (threshold_info or {}).get("breach", ""),
                }
            )


def main(argv=None) -> int:
    args = parse_args(argv)
    path = Path(args.input)
    records = load_latencies(path)
    summary = analyze(records, args.slo_threshold, args.failure_threshold)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.out_json:
        Path(args.out_json).write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if args.out_csv:
        write_summary_csv(summary, Path(args.out_csv))
    if summary["thresholds"]["p95_latency"]["breach"] or summary["thresholds"]["failure_rate"]["breach"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
