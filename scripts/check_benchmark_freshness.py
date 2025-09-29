#!/usr/bin/env python3
"""CLI to validate benchmark snapshot freshness."""
from __future__ import annotations

import argparse
import datetime as _dt
import json
from pathlib import Path
from typing import Any, Dict, List, Optional


DEFAULT_MAX_AGE_HOURS = 6.0


def _parse_timestamp(value: str) -> _dt.datetime:
    """Parse an ISO-8601 timestamp into a UTC-aware datetime."""

    if not value:
        raise ValueError("empty timestamp value")

    normalised = value.strip()
    if normalised.endswith("Z"):
        normalised = normalised[:-1] + "+00:00"

    try:
        parsed = _dt.datetime.fromisoformat(normalised)
    except ValueError as exc:  # pragma: no cover - error branch validated via tests
        raise ValueError(f"invalid ISO8601 timestamp: {value}") from exc

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_dt.timezone.utc)
    else:
        parsed = parsed.astimezone(_dt.timezone.utc)

    return parsed


def _normalise_target(raw: str) -> str:
    """Convert CLI target notation into the runtime snapshot key."""

    value = raw.strip()
    if ":" in value:
        symbol, mode = value.split(":", 1)
        key = f"{symbol}_{mode}"
    else:
        key = value
    return key


def evaluate_target(
    snapshot: Dict[str, Any],
    target: str,
    *,
    now: _dt.datetime,
    max_age_hours: float,
) -> Dict[str, Any]:
    """Evaluate freshness for a single benchmark target."""

    result: Dict[str, Any] = {
        "target": target,
        "errors": [],
    }

    benchmarks = snapshot.get("benchmarks", {}) or {}
    pipeline = snapshot.get("benchmark_pipeline", {}) or {}

    benchmark_ts_str = benchmarks.get(target)
    if benchmark_ts_str is None:
        result["errors"].append(f"benchmarks.{target} missing")
    else:
        try:
            benchmark_ts = _parse_timestamp(benchmark_ts_str)
            age_hours = (now - benchmark_ts).total_seconds() / 3600
            result["benchmarks_timestamp"] = benchmark_ts_str
            result["benchmarks_age_hours"] = age_hours
            if age_hours > max_age_hours:
                result["errors"].append(
                    f"benchmarks.{target} stale by {age_hours:.2f}h (limit {max_age_hours}h)"
                )
        except ValueError as exc:
            result["errors"].append(str(exc))

    pipeline_entry = pipeline.get(target)
    if pipeline_entry is None:
        result["errors"].append(f"benchmark_pipeline.{target} missing")
    else:
        latest_ts = pipeline_entry.get("latest_ts")
        if latest_ts is None:
            result["errors"].append(f"benchmark_pipeline.{target}.latest_ts missing")
        else:
            try:
                latest_dt = _parse_timestamp(latest_ts)
                latest_age_hours = (now - latest_dt).total_seconds() / 3600
                result["latest_ts"] = latest_ts
                result["latest_age_hours"] = latest_age_hours
                if latest_age_hours > max_age_hours:
                    result["errors"].append(
                        f"benchmark_pipeline.{target}.latest_ts stale by {latest_age_hours:.2f}h (limit {max_age_hours}h)"
                    )
            except ValueError as exc:
                result["errors"].append(str(exc))

        summary_ts = pipeline_entry.get("summary_generated_at")
        if summary_ts is None:
            result["errors"].append(
                f"benchmark_pipeline.{target}.summary_generated_at missing"
            )
        else:
            try:
                summary_dt = _parse_timestamp(summary_ts)
                summary_age_hours = (now - summary_dt).total_seconds() / 3600
                result["summary_generated_at"] = summary_ts
                result["summary_age_hours"] = summary_age_hours
                if summary_age_hours > max_age_hours:
                    result["errors"].append(
                        "benchmark_pipeline."
                        f"{target}.summary_generated_at stale by {summary_age_hours:.2f}h "
                        f"(limit {max_age_hours}h)"
                    )
            except ValueError as exc:
                result["errors"].append(str(exc))

    return result


def check_benchmark_freshness(
    snapshot_path: Path,
    targets: List[str],
    *,
    max_age_hours: float,
    now: Optional[_dt.datetime] = None,
) -> Dict[str, Any]:
    """Validate benchmark freshness for all requested targets."""

    if now is None:
        now = _dt.datetime.now(tz=_dt.timezone.utc)

    raw_snapshot = json.loads(snapshot_path.read_text())

    normalised_targets = [_normalise_target(t) for t in targets]

    evaluations = [
        evaluate_target(raw_snapshot, target, now=now, max_age_hours=max_age_hours)
        for target in normalised_targets
    ]

    errors = [err for entry in evaluations for err in entry.get("errors", [])]

    return {
        "ok": not errors,
        "max_age_hours": max_age_hours,
        "checked": evaluations,
        "errors": errors,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check benchmark freshness recorded in ops/runtime_snapshot.json"
    )
    parser.add_argument(
        "--snapshot",
        type=Path,
        default=Path("ops/runtime_snapshot.json"),
        help="Path to runtime snapshot JSON",
    )
    parser.add_argument(
        "--target",
        action="append",
        dest="targets",
        required=True,
        help="Symbol/mode pair (e.g. USDJPY:conservative or USDJPY_conservative)",
    )
    parser.add_argument(
        "--max-age-hours",
        type=float,
        default=DEFAULT_MAX_AGE_HOURS,
        help="Maximum allowed age in hours for benchmark timestamps",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    result = check_benchmark_freshness(
        snapshot_path=args.snapshot,
        targets=args.targets,
        max_age_hours=args.max_age_hours,
    )

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
