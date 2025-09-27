#!/usr/bin/env python3
"""State health checker.

Reads the latest `state.json`, evaluates EV sample counts / win-rate lower bounds /
slippage coefficients, and logs the results. Warnings are emitted when thresholds
are breached, optionally posting to webhooks and trimming history length.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import urllib.error
import urllib.request
from statistics import NormalDist
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple


DEFAULT_STATE = Path("runs/active/state.json")
DEFAULT_OUT = Path("ops/health/state_checks.json")


def _parse_webhook_urls(value: Optional[str]) -> List[str]:
    if not value:
        return []
    urls: List[str] = []
    for part in value.split(","):
        part = part.strip()
        if part:
            urls.append(part)
    return urls


def _post_webhook(url: str, payload: Dict[str, object], timeout: float = 5.0) -> Tuple[bool, str]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return True, f"status={resp.status}"
    except urllib.error.HTTPError as exc:
        return False, f"http_error={exc.code}"
    except urllib.error.URLError as exc:
        return False, f"url_error={exc.reason}"
    except Exception as exc:  # pragma: no cover
        return False, f"unexpected_error={type(exc).__name__}:{exc}"


def load_state(path: Path) -> Dict:
    with path.open() as f:
        return json.load(f)


def _normal_approx_lcb(alpha: float, beta: float, *, z: float) -> float:
    total = alpha + beta
    if total <= 0:
        return 0.0
    mean = alpha / total
    var = (alpha * beta) / ((total ** 2) * (total + 1)) if total > 1 else mean * (1 - mean)
    std = math.sqrt(max(var, 0.0))
    lcb = mean - z * std
    return max(0.0, min(1.0, lcb))


def summarize(state: Dict, *, min_bucket_sample: float, z_value: float) -> Dict[str, object]:
    ev_global = state.get("ev_global", {})
    alpha = float(ev_global.get("alpha", 0.0))
    beta = float(ev_global.get("beta", 0.0))
    total = alpha + beta
    win_mean = alpha / total if total > 0 else None
    win_lcb = _normal_approx_lcb(alpha, beta, z=z_value) if total > 0 else None

    buckets_summary: List[Dict[str, float | int]] = []
    ev_buckets = state.get("ev_buckets", {})
    for key, stats in ev_buckets.items():
        a = float(stats.get("alpha", 0.0))
        b = float(stats.get("beta", 0.0))
        samples = a + b
        bucket_mean = a / samples if samples > 0 else None
        bucket_lcb = _normal_approx_lcb(a, b, z=z_value) if samples > 0 else None
        buckets_summary.append({
            "bucket": key,
            "alpha": a,
            "beta": b,
            "samples": samples,
            "warn_low_samples": samples < min_bucket_sample,
            "win_mean": bucket_mean,
            "win_lcb": bucket_lcb,
        })

    slip = state.get("slip", {})
    slip_a = slip.get("a", {}) or {}

    return {
        "ev_total_samples": total,
        "ev_win_mean": win_mean if win_mean is not None else None,
        "ev_win_lcb": win_lcb if win_lcb is not None else None,
        "bucket_summaries": buckets_summary,
        "slip_a": slip_a,
    }


def build_warnings(summary: Dict, *, min_global_sample: float, min_win_lcb: float,
                   min_bucket_sample: float, min_bucket_win_lcb: float,
                   max_slip: float) -> List[str]:
    warnings: List[str] = []
    total = summary.get("ev_total_samples", 0.0) or 0.0
    if total < min_global_sample:
        warnings.append(f"global sample count low: {total:.1f} < {min_global_sample}")

    global_lcb = summary.get("ev_win_lcb")
    if isinstance(global_lcb, (int, float)) and global_lcb < min_win_lcb:
        warnings.append(f"global win-rate LCB low: {global_lcb:.3f} < {min_win_lcb}")

    for bucket in summary.get("bucket_summaries", []):
        samples = bucket.get("samples", 0.0) or 0.0
        if samples < min_bucket_sample:
            warnings.append(f"bucket {bucket['bucket']} samples={samples:.1f} below threshold {min_bucket_sample}")
        lcb = bucket.get("win_lcb")
        if isinstance(lcb, (int, float)) and lcb < min_bucket_win_lcb:
            warnings.append(f"bucket {bucket['bucket']} win_lcb={lcb:.3f} below {min_bucket_win_lcb}")

    slip_a = summary.get("slip_a", {}) or {}
    for band, value in slip_a.items():
        try:
            v = float(value)
        except (TypeError, ValueError):
            warnings.append(f"slip coefficient {band} invalid: {value}")
            continue
        if v > max_slip:
            warnings.append(f"slip coefficient {band}={v:.3f} exceeds limit {max_slip}")
        if v < 0:
            warnings.append(f"slip coefficient {band} negative: {v:.3f}")

    return warnings


def load_history(path: Path) -> List[Dict]:
    if not path.exists():
        return []
    try:
        with path.open() as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []


def save_history(path: Path, history: List[Dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def rotate_history(history: List[Dict], record: Dict, limit: int) -> List[Dict]:
    updated = list(history)
    updated.append(record)
    if limit > 0 and len(updated) > limit:
        updated = updated[-limit:]
    return updated


def build_record(state_path: Path, summary: Dict, warnings: List[str], *, confidence: float,
                 thresholds: Dict[str, float]) -> Dict[str, object]:
    checked_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "checked_at": checked_at,
        "state_path": str(state_path),
        "metrics": {
            "ev_total_samples": summary["ev_total_samples"],
            "ev_win_mean": summary["ev_win_mean"],
            "ev_win_lcb": summary["ev_win_lcb"],
            "slip_a": summary["slip_a"],
        },
        "bucket_samples": [
            {
                "bucket": b["bucket"],
                "samples": b["samples"],
                "win_mean": b["win_mean"],
                "win_lcb": b["win_lcb"],
            }
            for b in summary["bucket_summaries"]
        ],
        "warnings": warnings,
        "config": {
            "confidence": confidence,
            **thresholds,
        },
    }


def build_webhook_payload(record: Dict[str, object]) -> Dict[str, object]:
    return {
        "event": "state_health_warning",
        "state_path": record["state_path"],
        "checked_at": record["checked_at"],
        "warnings": record["warnings"],
        "metrics": record["metrics"],
    }


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Check health metrics of state.json")
    parser.add_argument("--state", default=str(DEFAULT_STATE), help="Path to state.json")
    parser.add_argument("--json-out", default=str(DEFAULT_OUT), help="Health history JSON path")
    parser.add_argument("--min-global-sample", type=float, default=40.0, help="Warn if global alpha+beta below this")
    parser.add_argument("--min-win-lcb", type=float, default=0.45, help="Warn if global win-rate lower bound below this")
    parser.add_argument("--min-bucket-sample", type=float, default=10.0, help="Warn if bucket alpha+beta below this")
    parser.add_argument("--min-bucket-win-lcb", type=float, default=0.35, help="Warn if bucket win-rate lower bound below this")
    parser.add_argument("--max-slip", type=float, default=0.5, help="Warn if slip coefficient exceeds this")
    parser.add_argument("--confidence", type=float, default=0.95, help="Confidence level for win-rate LCB (normal approx)")
    parser.add_argument("--history-limit", type=int, default=90, help="Keep at most this many history records (0=unbounded)")
    parser.add_argument("--webhook", default=None, help="Comma separated webhook URLs for warning alerts")
    parser.add_argument("--fail-on-warning", action="store_true", help="Exit with code 2 if warnings were generated")
    parser.add_argument("--dry-run", action="store_true", help="Do not write history file")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    state_path = Path(args.state)
    if not state_path.exists():
        print(json.dumps({"error": "state_not_found", "state": str(state_path)}))
        return 1

    state = load_state(state_path)
    conf = max(0.5, min(args.confidence, 0.999))
    z_value = abs(NormalDist().inv_cdf(0.5 + conf / 2.0))

    summary = summarize(state, min_bucket_sample=args.min_bucket_sample, z_value=z_value)
    warnings = build_warnings(
        summary,
        min_global_sample=args.min_global_sample,
        min_win_lcb=args.min_win_lcb,
        min_bucket_sample=args.min_bucket_sample,
        min_bucket_win_lcb=args.min_bucket_win_lcb,
        max_slip=args.max_slip,
    )

    thresholds = {
        "min_global_sample": args.min_global_sample,
        "min_win_lcb": args.min_win_lcb,
        "min_bucket_sample": args.min_bucket_sample,
        "min_bucket_win_lcb": args.min_bucket_win_lcb,
        "max_slip": args.max_slip,
    }
    record = build_record(
        state_path,
        summary,
        warnings,
        confidence=conf,
        thresholds=thresholds,
    )

    print(json.dumps(record, ensure_ascii=False))

    deliveries: List[Dict[str, object]] = []
    webhook_urls = _parse_webhook_urls(args.webhook)
    if warnings and webhook_urls and not args.dry_run:
        payload = build_webhook_payload(record)
        for url in webhook_urls:
            ok, detail = _post_webhook(url, payload)
            deliveries.append({"url": url, "ok": ok, "detail": detail})
        record["webhook"] = deliveries

    if not args.dry_run:
        history_path = Path(args.json_out)
        history = load_history(history_path)
        history = rotate_history(history, record, args.history_limit)
        save_history(history_path, history)
    elif deliveries:
        record["webhook"] = deliveries

    if warnings and args.fail_on_warning:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
