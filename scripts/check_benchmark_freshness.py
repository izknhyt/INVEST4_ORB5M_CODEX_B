#!/usr/bin/env python3
"""CLI to validate benchmark snapshot freshness."""
from __future__ import annotations

import argparse
import datetime as _dt
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


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


def _extract_symbol(target: str) -> str:
    """Return the symbol portion from a normalised target name."""

    if ":" in target:
        symbol, _ = target.split(":", 1)
        return symbol
    if "_" in target:
        symbol, _ = target.split("_", 1)
        return symbol
    return target


def _resolve_ingest_metadata(
    snapshot: Dict[str, Any],
    target: str,
    *,
    ingest_timeframe: Optional[str],
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Locate ingestion metadata for the symbol associated with *target*."""

    ingest_meta = snapshot.get("ingest_meta") or {}
    if not isinstance(ingest_meta, dict):
        return None, None

    symbol = _extract_symbol(target)
    lookup_keys: List[str] = []
    if ingest_timeframe:
        lookup_keys.append(f"{symbol}_{ingest_timeframe}")
    lookup_keys.extend(
        key
        for key in ingest_meta.keys()
        if isinstance(key, str) and key.startswith(f"{symbol}_") and key not in lookup_keys
    )

    for key in lookup_keys:
        meta = ingest_meta.get(key)
        if isinstance(meta, dict):
            return key, meta

    return None, None


def _metadata_indicates_synthetic(meta: Dict[str, Any]) -> bool:
    """Return True when ingestion metadata records synthetic extensions."""

    if bool(meta.get("synthetic_extension")):
        return True

    chain = meta.get("source_chain")
    if isinstance(chain, Iterable):
        for entry in chain:
            if isinstance(entry, dict) and entry.get("source") == "synthetic_local":
                return True
    return False


def _coerce_freshness_minutes(value: Any) -> Optional[float]:
    """Return a float representation of *value* when possible."""

    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _normalise_string_sequence(values: Any) -> List[str]:
    """Return a list of string entries extracted from *values*."""

    if not isinstance(values, list):
        return []

    result: List[str] = []
    for item in values:
        if isinstance(item, str) and item:
            result.append(item)
        elif isinstance(item, dict):
            source = item.get("source")
            if isinstance(source, str) and source:
                result.append(source)
    return result


def evaluate_target(
    snapshot: Dict[str, Any],
    target: str,
    *,
    now: _dt.datetime,
    max_age_hours: float,
    ingest_meta_key: Optional[str] = None,
    ingest_meta: Optional[Dict[str, Any]] = None,
    downgrade_stale_to_advisory: bool = False,
) -> Dict[str, Any]:
    """Evaluate freshness for a single benchmark target."""

    result: Dict[str, Any] = {
        "target": target,
        "errors": [],
        "advisories": [],
    }

    if ingest_meta_key:
        result["ingest_meta_key"] = ingest_meta_key
    if ingest_meta is not None:
        meta_summary: Dict[str, Any] = {
            "synthetic_extension": bool(ingest_meta.get("synthetic_extension")),
            "primary_source": ingest_meta.get("primary_source"),
        }

        freshness_minutes = _coerce_freshness_minutes(
            ingest_meta.get("freshness_minutes")
        )
        if freshness_minutes is not None:
            meta_summary["freshness_minutes"] = freshness_minutes
        last_ingest_at = ingest_meta.get("last_ingest_at")
        if isinstance(last_ingest_at, str) and last_ingest_at:
            meta_summary["last_ingest_at"] = last_ingest_at

        fallbacks = _normalise_string_sequence(ingest_meta.get("fallbacks"))
        if fallbacks:
            meta_summary["fallbacks"] = fallbacks
        source_chain = _normalise_string_sequence(ingest_meta.get("source_chain"))
        if source_chain:
            meta_summary["source_chain"] = source_chain
        backup_path = ingest_meta.get("local_backup_path")
        if isinstance(backup_path, str) and backup_path:
            meta_summary["local_backup_path"] = backup_path

        result["ingest_metadata"] = meta_summary

    def _append_issue(container: List[str], message: str) -> None:
        container.append(message)

    def _should_downgrade(message: str) -> bool:
        if not downgrade_stale_to_advisory:
            return False

        if "stale" in message:
            return True

        if message.startswith("benchmark_pipeline."):
            return True

        if message.startswith("benchmarks."):
            return True

        return False

    def _record_issue(message: str) -> None:
        if _should_downgrade(message):
            _append_issue(result["advisories"], message)
        else:
            _append_issue(result["errors"], message)

    benchmarks = snapshot.get("benchmarks", {}) or {}
    pipeline = snapshot.get("benchmark_pipeline", {}) or {}

    benchmark_ts_str = benchmarks.get(target)
    if benchmark_ts_str is None:
        _record_issue(f"benchmarks.{target} missing")
    else:
        try:
            benchmark_ts = _parse_timestamp(benchmark_ts_str)
            age_hours = (now - benchmark_ts).total_seconds() / 3600
            result["benchmarks_timestamp"] = benchmark_ts_str
            result["benchmarks_age_hours"] = age_hours
            if age_hours > max_age_hours:
                _record_issue(
                    f"benchmarks.{target} stale by {age_hours:.2f}h (limit {max_age_hours}h)"
                )
        except ValueError as exc:
            _record_issue(str(exc))

    pipeline_entry = pipeline.get(target)
    if pipeline_entry is None:
        _record_issue(f"benchmark_pipeline.{target} missing")
    else:
        latest_ts = pipeline_entry.get("latest_ts")
        if latest_ts is None:
            _record_issue(f"benchmark_pipeline.{target}.latest_ts missing")
        else:
            try:
                latest_dt = _parse_timestamp(latest_ts)
                latest_age_hours = (now - latest_dt).total_seconds() / 3600
                result["latest_ts"] = latest_ts
                result["latest_age_hours"] = latest_age_hours
                if latest_age_hours > max_age_hours:
                    _record_issue(
                        f"benchmark_pipeline.{target}.latest_ts stale by {latest_age_hours:.2f}h (limit {max_age_hours}h)"
                    )
            except ValueError as exc:
                _record_issue(str(exc))

        summary_ts = pipeline_entry.get("summary_generated_at")
        if summary_ts is None:
            _record_issue(
                f"benchmark_pipeline.{target}.summary_generated_at missing"
            )
        else:
            try:
                summary_dt = _parse_timestamp(summary_ts)
                summary_age_hours = (now - summary_dt).total_seconds() / 3600
                result["summary_generated_at"] = summary_ts
                result["summary_age_hours"] = summary_age_hours
                if summary_age_hours > max_age_hours:
                    _record_issue(
                        "benchmark_pipeline."
                        f"{target}.summary_generated_at stale by {summary_age_hours:.2f}h "
                        f"(limit {max_age_hours}h)"
                    )
            except ValueError as exc:
                _record_issue(str(exc))

    return result


def check_benchmark_freshness(
    snapshot_path: Path,
    targets: List[str],
    *,
    max_age_hours: float,
    ingest_timeframe: Optional[str] = None,
    now: Optional[_dt.datetime] = None,
) -> Dict[str, Any]:
    """Validate benchmark freshness for all requested targets."""

    if now is None:
        now = _dt.datetime.now(tz=_dt.timezone.utc)

    raw_snapshot = json.loads(snapshot_path.read_text())

    normalised_targets = [_normalise_target(t) for t in targets]

    evaluations = []
    for target in normalised_targets:
        meta_key, meta = _resolve_ingest_metadata(
            raw_snapshot,
            target,
            ingest_timeframe=ingest_timeframe,
        )
        downgrade = bool(meta and _metadata_indicates_synthetic(meta))
        evaluations.append(
            evaluate_target(
                raw_snapshot,
                target,
                now=now,
                max_age_hours=max_age_hours,
                ingest_meta_key=meta_key,
                ingest_meta=meta,
                downgrade_stale_to_advisory=downgrade,
            )
        )

    errors = [err for entry in evaluations for err in entry.get("errors", [])]
    advisories = [note for entry in evaluations for note in entry.get("advisories", [])]

    return {
        "ok": not errors,
        "max_age_hours": max_age_hours,
        "checked": evaluations,
        "errors": errors,
        "advisories": advisories,
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
    parser.add_argument(
        "--ingest-timeframe",
        default="5m",
        help="Expected ingestion timeframe (used to locate ingest metadata)",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    result = check_benchmark_freshness(
        snapshot_path=args.snapshot,
        targets=args.targets,
        max_age_hours=args.max_age_hours,
        ingest_timeframe=args.ingest_timeframe,
    )

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
