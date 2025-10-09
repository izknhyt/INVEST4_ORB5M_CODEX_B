#!/usr/bin/env python3
"""Quick data quality audit for 5m OHLC CSV files."""
from __future__ import annotations
import argparse
import csv
import json
import math
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import median
from typing import Dict, List, Sequence, Set, Tuple

REQUIRED_COLS = ["timestamp", "symbol", "tf", "o", "h", "l", "c", "spread"]
DEFAULT_INTERVAL_MINUTES = 5.0


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
    p.add_argument("--expected-interval-minutes", type=float, default=None,
                   help="Override the expected bar interval in minutes (default: auto-detect from tf column or timestamps)")
    p.add_argument("--start-timestamp", default=None,
                   help="Optional ISO-8601 timestamp (UTC) marking the inclusive start of the audit window")
    p.add_argument("--end-timestamp", default=None,
                   help="Optional ISO-8601 timestamp (UTC) marking the inclusive end of the audit window")
    p.add_argument("--min-gap-minutes", type=float, default=0.0,
                   help="Ignore gaps shorter than this many minutes when aggregating and exporting results (default: 0.0)")
    p.add_argument("--out-gap-json", default=None,
                   help="Optional JSON output path containing the complete gap inventory after filters")
    p.add_argument("--max-duplicate-report", type=int, default=20,
                   help="Maximum number of duplicate timestamp groups retained in the summary payload (default: 20)")
    p.add_argument(
        "--min-duplicate-occurrences",
        type=int,
        default=2,
        help="Only include duplicate timestamp groups with at least this many occurrences in summaries and exports (default: 2)",
    )
    p.add_argument("--out-duplicates-csv", default=None,
                   help="Optional CSV output path containing duplicate timestamp details")
    p.add_argument("--out-duplicates-json", default=None,
                   help="Optional JSON output path containing duplicate timestamp details")
    p.add_argument(
        "--calendar-day-summary",
        action="store_true",
        help="Include per-calendar-day coverage metrics in the summary payload (UTC)",
    )
    p.add_argument(
        "--calendar-day-max-report",
        type=int,
        default=10,
        help="Maximum number of calendar day entries retained in the summary payload (default: 10)",
    )
    p.add_argument(
        "--calendar-day-coverage-threshold",
        type=float,
        default=0.98,
        help=(
            "Coverage ratio threshold used to flag calendar days with insufficient data "
            "when --calendar-day-summary is enabled (default: 0.98)"
        ),
    )
    p.add_argument(
        "--fail-under-coverage",
        type=float,
        default=None,
        help=(
            "Exit with status 1 when the overall coverage ratio falls below this threshold "
            "(0-1, optional)"
        ),
    )
    p.add_argument(
        "--fail-on-calendar-day-warnings",
        action="store_true",
        help=(
            "Exit with status 1 when calendar-day coverage warnings are present in the summary "
            "(requires --calendar-day-summary)"
        ),
    )
    return p.parse_args(argv)


def _parse_timestamp(value: str) -> datetime:
    raw_ts = value.strip().replace(" ", "T")
    if raw_ts.endswith("Z"):
        raw_ts = raw_ts[:-1]
    ts = datetime.fromisoformat(raw_ts)
    if ts.tzinfo is not None:
        ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
    return ts


def parse_row(row: Dict[str, str]):
    ts = _parse_timestamp(row["timestamp"])
    tf = row.get("tf", "").strip()
    symbol = row.get("symbol")
    return ts, tf, symbol


def _parse_tf_minutes(tf_value: str) -> float | None:
    if not tf_value:
        return None
    match = re.search(r"(?i)(\d+(?:\.\d+)?)([smhd]?)", tf_value.strip())
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2).lower()
    if unit in ("", "m"):
        return value
    if unit == "s":
        return value / 60.0
    if unit == "h":
        return value * 60.0
    if unit == "d":
        return value * 1440.0
    return None


def _detect_interval_from_diffs(timestamps: Sequence[datetime]) -> float | None:
    if not timestamps:
        return None
    sorted_unique = sorted(set(timestamps))
    if len(sorted_unique) < 2:
        return None
    diffs: List[float] = []
    last = sorted_unique[0]
    for ts in sorted_unique[1:]:
        diff = (ts - last).total_seconds() / 60.0
        if diff > 0:
            diffs.append(diff)
        last = ts
    if not diffs:
        return None
    return median(diffs)


def _resolve_expected_interval(
    override_minutes: float | None,
    tf_minutes_counter: Counter,
    timestamps: Sequence[datetime],
) -> Tuple[float, str]:
    if override_minutes and override_minutes > 0:
        return override_minutes, "override"
    if tf_minutes_counter:
        value, _ = max(tf_minutes_counter.items(), key=lambda item: (item[1], -item[0]))
        return value, "tf_column"
    detected = _detect_interval_from_diffs(timestamps)
    if detected and detected > 0:
        return detected, "observed_diff"
    return DEFAULT_INTERVAL_MINUTES, "default"


def _analyse_timestamps(
    timestamps: Sequence[datetime],
    *,
    interval_minutes: float,
    max_gap_report: int,
    capture_gap_details: bool,
    min_gap_minutes: float = 0.0,
) -> Tuple[
    int,
    int,
    List[str],
    List[Dict[str, object]],
    List[Dict[str, object]],
    List[float],
    float,
    int,
    float,
    int,
    float,
    int,
]:
    duplicates = 0
    monotonic_errors = 0
    issues: List[str] = []
    gap_samples: List[Dict[str, object]] = []
    full_gap_details: List[Dict[str, object]] | None = [] if capture_gap_details else None
    gap_minutes: List[float] = []
    total_gap_minutes = 0.0
    missing_rows_estimate = 0
    irregular_gap_count = 0
    ignored_gap_count = 0
    ignored_gap_minutes = 0.0
    ignored_missing_rows_estimate = 0
    last_ts: datetime | None = None

    for ts in timestamps:
        if last_ts is None:
            last_ts = ts
            continue
        if ts == last_ts:
            duplicates += 1
            last_ts = ts
            continue
        if ts < last_ts:
            monotonic_errors += 1
            issues.append(
                f"non-monotonic timestamp: {last_ts.isoformat()} -> {ts.isoformat()}"
            )
            last_ts = ts
            continue

        diff = ts - last_ts
        diff_minutes = diff.total_seconds() / 60.0
        expected_steps = diff_minutes / interval_minutes if interval_minutes > 0 else float("inf")
        rounded_steps = round(expected_steps) if math.isfinite(expected_steps) else 0
        missing_rows = max(int(rounded_steps) - 1, 0) if math.isfinite(expected_steps) else 0
        irregular = not math.isclose(expected_steps, rounded_steps, rel_tol=1e-9, abs_tol=1e-9)

        if not math.isclose(expected_steps, 1.0, rel_tol=1e-9, abs_tol=1e-9):
            if diff_minutes < min_gap_minutes:
                ignored_gap_count += 1
                ignored_gap_minutes += diff_minutes
                ignored_missing_rows_estimate += missing_rows
                last_ts = ts
                continue
            gap_record = {
                "start_timestamp": last_ts.isoformat(),
                "end_timestamp": ts.isoformat(),
                "gap_minutes": diff_minutes,
                "expected_intervals": expected_steps,
                "missing_rows_estimate": missing_rows,
                "irregular": irregular,
            }
            if len(gap_samples) < max_gap_report:
                gap_samples.append(gap_record)
            if full_gap_details is not None:
                full_gap_details.append(gap_record)
            gap_minutes.append(diff_minutes)
            total_gap_minutes += diff_minutes
            missing_rows_estimate += missing_rows
            if irregular:
                irregular_gap_count += 1
                issues.append(
                    "irregular gap length: "
                    f"{last_ts.isoformat()} -> {ts.isoformat()} ({diff_minutes:.2f} minutes)"
                )

        last_ts = ts

    return (
        duplicates,
        monotonic_errors,
        issues,
        gap_samples,
        full_gap_details if full_gap_details is not None else gap_samples,
        gap_minutes,
        total_gap_minutes,
        missing_rows_estimate,
        irregular_gap_count,
        ignored_gap_count,
        ignored_gap_minutes,
        ignored_missing_rows_estimate,
    )


def _build_calendar_day_summary(
    timestamps: Sequence[datetime],
    *,
    interval_minutes: float,
    max_gap_report: int,
    min_gap_minutes: float,
    filtered_duplicate_details: Sequence[Dict[str, object]],
    coverage_threshold: float | None,
    max_report: int,
):
    if not timestamps:
        expected_rows_per_day = (
            int(round(1440.0 / interval_minutes)) if interval_minutes > 0 else None
        )
        return {
            "coverage_threshold": coverage_threshold,
            "expected_rows_per_day": expected_rows_per_day,
            "count": 0,
            "details": [],
            "details_truncated": False,
            "warnings": [],
            "warnings_truncated": False,
        }

    sorted_timestamps = sorted(timestamps)
    buckets: dict[date, List[datetime]] = defaultdict(list)
    for ts in sorted_timestamps:
        buckets[ts.date()].append(ts)

    entries: List[Dict[str, object]] = []
    for day in sorted(buckets.keys()):
        day_timestamps = buckets[day]
        (
            _,
            _,
            _,
            _,
            _,
            gap_minutes,
            total_gap_minutes,
            missing_rows_estimate,
            _,
            ignored_gap_count,
            ignored_gap_minutes,
            ignored_missing_rows_estimate,
        ) = _analyse_timestamps(
            day_timestamps,
            interval_minutes=interval_minutes,
            max_gap_report=max_gap_report,
            capture_gap_details=False,
            min_gap_minutes=min_gap_minutes,
        )

        unique_count = len(set(day_timestamps))
        expected_rows = None
        coverage_ratio = None
        if day_timestamps and interval_minutes > 0:
            span_minutes = (
                day_timestamps[-1] - day_timestamps[0]
            ).total_seconds() / 60.0
            expected_rows = int(round(span_minutes / interval_minutes)) + 1
            if expected_rows > 0:
                coverage_ratio = unique_count / expected_rows

        duplicates_for_day = [
            item
            for item in filtered_duplicate_details
            if _parse_timestamp(item["timestamp"]).date() == day
        ]
        duplicates = sum(item["occurrences"] - 1 for item in duplicates_for_day)
        duplicate_groups = len(duplicates_for_day)
        duplicate_max_occurrences = max(
            (item["occurrences"] for item in duplicates_for_day),
            default=0,
        )

        entries.append(
            {
                "date": day.isoformat(),
                "start_timestamp": day_timestamps[0].isoformat(),
                "end_timestamp": day_timestamps[-1].isoformat(),
                "row_count": len(day_timestamps),
                "unique_timestamps": unique_count,
                "missing_rows_estimate": missing_rows_estimate,
                "gap_count": len(gap_minutes),
                "max_gap_minutes": max(gap_minutes) if gap_minutes else 0.0,
                "total_gap_minutes": total_gap_minutes,
                "ignored_gap_count": ignored_gap_count,
                "ignored_gap_minutes": ignored_gap_minutes,
                "ignored_missing_rows_estimate": ignored_missing_rows_estimate,
                "coverage_ratio": coverage_ratio,
                "expected_rows": expected_rows,
                "duplicates": duplicates,
                "duplicate_groups": duplicate_groups,
                "duplicate_max_occurrences": duplicate_max_occurrences,
            }
        )

    def _coverage_sort_key(item: Dict[str, object]) -> tuple[float, str]:
        coverage = item.get("coverage_ratio")
        if coverage is None:
            return (float("inf"), item["date"])
        return (coverage, item["date"])

    sorted_entries = sorted(entries, key=_coverage_sort_key)
    max_report = max(1, max_report)
    details = sorted_entries[:max_report]
    warnings_all = [
        entry
        for entry in sorted_entries
        if entry["coverage_ratio"] is not None
        and coverage_threshold is not None
        and entry["coverage_ratio"] < coverage_threshold
    ]
    warnings = warnings_all[:max_report]

    expected_rows_per_day = (
        int(round(1440.0 / interval_minutes)) if interval_minutes > 0 else None
    )

    return {
        "coverage_threshold": coverage_threshold,
        "expected_rows_per_day": expected_rows_per_day,
        "count": len(entries),
        "details": details,
        "details_truncated": len(sorted_entries) > len(details),
        "warnings": warnings,
        "warnings_truncated": len(warnings_all) > len(warnings),
    }


def _audit_internal(
    csv_path: Path,
    symbol: str | None = None,
    *,
    max_gap_report: int = 20,
    max_duplicate_report: int = 20,
    capture_gap_details: bool = False,
    expected_interval_minutes: float | None = None,
    start_timestamp: datetime | None = None,
    end_timestamp: datetime | None = None,
    min_gap_minutes: float = 0.0,
    min_duplicate_occurrences: int = 2,
    calendar_day_summary: bool = False,
    calendar_day_max_report: int = 10,
    calendar_day_coverage_threshold: float | None = None,
):
    missing_cols = 0
    bad_rows = 0
    tf_counter = Counter()
    tf_minutes_counter = Counter()
    symbol_counter = Counter()
    timestamps: List[datetime] = []
    total_rows = 0

    timestamp_line_numbers: defaultdict[datetime, List[int]] = defaultdict(list)

    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for line_number, row in enumerate(reader, start=2):
            if any(col not in row for col in REQUIRED_COLS):
                missing_cols += 1
                continue
            if symbol and row.get("symbol") != symbol:
                continue
            try:
                ts, tf, sym = parse_row(row)
                float(row["o"])
                float(row["h"])
                float(row["l"])
                float(row["c"])
            except Exception:
                bad_rows += 1
                continue

            if start_timestamp and ts < start_timestamp:
                continue
            if end_timestamp and ts > end_timestamp:
                continue

            total_rows += 1
            tf_counter[tf] += 1
            symbol_counter[sym] += 1
            timestamps.append(ts)
            tf_minutes = _parse_tf_minutes(tf)
            if tf_minutes and tf_minutes > 0:
                tf_minutes_counter[tf_minutes] += 1
            timestamp_line_numbers[ts].append(line_number)

    duplicate_details: List[Dict[str, object]] = []
    for ts in sorted(timestamp_line_numbers.keys()):
        line_numbers = timestamp_line_numbers[ts]
        if len(line_numbers) <= 1:
            continue
        duplicate_details.append(
            {
                "timestamp": ts.isoformat(),
                "occurrences": len(line_numbers),
                "line_numbers": line_numbers,
            }
        )

    unique_ts: Set[datetime] = set(timestamps)
    earliest_ts = min(timestamps) if timestamps else None
    latest_ts = max(timestamps) if timestamps else None

    interval_minutes, interval_source = _resolve_expected_interval(
        expected_interval_minutes,
        tf_minutes_counter,
        timestamps,
    )
    # Ensure a sane positive interval for downstream calculations.
    if interval_minutes <= 0:
        interval_minutes = DEFAULT_INTERVAL_MINUTES
        interval_source = "default"

    effective_min_gap = max(0.0, min_gap_minutes)

    (
        duplicates,
        monotonic_errors,
        issues,
        gap_samples,
        full_gap_details,
        gap_minutes,
        total_gap_minutes,
        missing_rows_estimate,
        irregular_gap_count,
        ignored_gap_count,
        ignored_gap_minutes,
        ignored_missing_rows_estimate,
    ) = _analyse_timestamps(
        timestamps,
        interval_minutes=interval_minutes,
        max_gap_report=max_gap_report,
        capture_gap_details=capture_gap_details,
        min_gap_minutes=effective_min_gap,
    )

    # Prefer aggregate duplicate counts computed across the full timestamp set
    # so non-consecutive repeats are captured as well.
    duplicate_details_sorted = sorted(
        duplicate_details,
        key=lambda item: (-item["occurrences"], item["timestamp"]),
    )
    min_duplicate_occurrences = max(2, min_duplicate_occurrences)
    filtered_duplicate_details = [
        item
        for item in duplicate_details_sorted
        if item["occurrences"] >= min_duplicate_occurrences
    ]
    duplicates = sum(item["occurrences"] - 1 for item in filtered_duplicate_details)
    duplicate_groups = len(filtered_duplicate_details)
    duplicate_samples = filtered_duplicate_details[: max(1, max_duplicate_report)]
    duplicates_truncated = len(filtered_duplicate_details) > len(duplicate_samples)

    ignored_duplicate_groups = len(duplicate_details_sorted) - duplicate_groups
    ignored_duplicate_rows = sum(
        item["occurrences"] - 1
        for item in duplicate_details_sorted
        if item["occurrences"] < min_duplicate_occurrences
    )

    duplicate_max_occurrences = (
        max((item["occurrences"] for item in filtered_duplicate_details), default=0)
    )
    duplicate_first_timestamp = None
    duplicate_last_timestamp = None
    duplicate_timestamp_span_minutes = None
    if filtered_duplicate_details:
        duplicate_first_timestamp = min(
            item["timestamp"] for item in filtered_duplicate_details
        )
        duplicate_last_timestamp = max(
            item["timestamp"] for item in filtered_duplicate_details
        )
        first_dt = _parse_timestamp(duplicate_first_timestamp)
        last_dt = _parse_timestamp(duplicate_last_timestamp)
        if last_dt >= first_dt:
            duplicate_timestamp_span_minutes = (
                last_dt - first_dt
            ).total_seconds() / 60.0
        else:
            duplicate_timestamp_span_minutes = 0.0

    if len(tf_minutes_counter) > 1:
        distinct_intervals = ", ".join(
            f"{value:g}m" for value in sorted(tf_minutes_counter.keys())
        )
        issues.append(f"multiple timeframe values detected: {distinct_intervals}")

    expected_rows = None
    coverage_ratio = None
    if (
        earliest_ts is not None
        and latest_ts is not None
        and latest_ts >= earliest_ts
        and interval_minutes > 0
    ):
        span_minutes = (latest_ts - earliest_ts).total_seconds() / 60.0
        expected_rows = int(round(span_minutes / interval_minutes)) + 1
        if expected_rows > 0:
            coverage_ratio = len(unique_ts) / expected_rows

    summary = {
        "csv": str(csv_path),
        "symbol_filter": symbol,
        "start_timestamp_filter": start_timestamp.isoformat() if start_timestamp else None,
        "end_timestamp_filter": end_timestamp.isoformat() if end_timestamp else None,
        "missing_cols": missing_cols,
        "bad_rows": bad_rows,
        "duplicates": duplicates,
        "duplicate_groups": duplicate_groups,
        "duplicate_details": duplicate_samples,
        "duplicate_details_truncated": duplicates_truncated,
        "duplicate_max_occurrences": duplicate_max_occurrences,
        "duplicate_first_timestamp": duplicate_first_timestamp,
        "duplicate_last_timestamp": duplicate_last_timestamp,
        "duplicate_timestamp_span_minutes": duplicate_timestamp_span_minutes,
        "duplicate_min_occurrences": min_duplicate_occurrences,
        "ignored_duplicate_groups": ignored_duplicate_groups,
        "ignored_duplicate_rows": ignored_duplicate_rows,
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
        "expected_interval_minutes": interval_minutes,
        "expected_interval_source": interval_source,
        "min_gap_minutes": effective_min_gap,
        "ignored_gap_count": ignored_gap_count,
        "ignored_gap_minutes": ignored_gap_minutes,
        "ignored_missing_rows_estimate": ignored_missing_rows_estimate,
    }
    if calendar_day_summary:
        summary["calendar_day_summary"] = _build_calendar_day_summary(
            timestamps,
            interval_minutes=interval_minutes,
            max_gap_report=max(1, max_gap_report),
            min_gap_minutes=effective_min_gap,
            filtered_duplicate_details=filtered_duplicate_details,
            coverage_threshold=calendar_day_coverage_threshold,
            max_report=calendar_day_max_report,
        )
    return summary, full_gap_details, filtered_duplicate_details


def audit(
    csv_path: Path,
    symbol: str | None = None,
    *,
    max_gap_report: int = 20,
    max_duplicate_report: int = 20,
    expected_interval_minutes: float | None = None,
    start_timestamp: datetime | None = None,
    end_timestamp: datetime | None = None,
    min_gap_minutes: float = 0.0,
    min_duplicate_occurrences: int = 2,
    calendar_day_summary: bool = False,
    calendar_day_max_report: int = 10,
    calendar_day_coverage_threshold: float | None = None,
) -> Dict[str, object]:
    summary, _, _ = _audit_internal(
        csv_path,
        symbol,
        max_gap_report=max_gap_report,
        max_duplicate_report=max_duplicate_report,
        capture_gap_details=False,
        expected_interval_minutes=expected_interval_minutes,
        start_timestamp=start_timestamp,
        end_timestamp=end_timestamp,
        min_gap_minutes=min_gap_minutes,
        min_duplicate_occurrences=min_duplicate_occurrences,
        calendar_day_summary=calendar_day_summary,
        calendar_day_max_report=calendar_day_max_report,
        calendar_day_coverage_threshold=calendar_day_coverage_threshold,
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


def _write_duplicate_csv(path: Path, duplicates: List[Dict[str, object]]):
    fieldnames = ["timestamp", "occurrences", "line_numbers"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for item in duplicates:
            writer.writerow(
                {
                    "timestamp": item["timestamp"],
                    "occurrences": item["occurrences"],
                    "line_numbers": ",".join(str(num) for num in item["line_numbers"]),
                }
            )


def main(argv=None):
    args = parse_args(argv)
    csv_path = Path(args.csv)
    if not csv_path.exists():
        raise SystemExit(f"CSV not found: {csv_path}")
    if getattr(args, "min_gap_minutes", 0.0) is not None and args.min_gap_minutes < 0:
        raise SystemExit("--min-gap-minutes must be non-negative")
    if (
        getattr(args, "min_duplicate_occurrences", None) is not None
        and args.min_duplicate_occurrences < 2
    ):
        raise SystemExit("--min-duplicate-occurrences must be at least 2")
    if (
        getattr(args, "calendar_day_max_report", None) is not None
        and args.calendar_day_max_report < 1
    ):
        raise SystemExit("--calendar-day-max-report must be at least 1")
    if getattr(args, "calendar_day_coverage_threshold", None) is not None:
        threshold = args.calendar_day_coverage_threshold
        if threshold < 0 or threshold > 1:
            raise SystemExit("--calendar-day-coverage-threshold must be between 0 and 1")
    if getattr(args, "fail_under_coverage", None) is not None:
        coverage_threshold = args.fail_under_coverage
        if coverage_threshold < 0 or coverage_threshold > 1:
            raise SystemExit("--fail-under-coverage must be between 0 and 1")
    if (
        getattr(args, "fail_on_calendar_day_warnings", False)
        and not getattr(args, "calendar_day_summary", False)
    ):
        raise SystemExit(
            "--fail-on-calendar-day-warnings requires --calendar-day-summary"
        )
    start_ts = None
    if getattr(args, "start_timestamp", None):
        try:
            start_ts = _parse_timestamp(args.start_timestamp)
        except Exception as exc:
            raise SystemExit(f"invalid --start-timestamp value: {args.start_timestamp}") from exc
    end_ts = None
    if getattr(args, "end_timestamp", None):
        try:
            end_ts = _parse_timestamp(args.end_timestamp)
        except Exception as exc:
            raise SystemExit(f"invalid --end-timestamp value: {args.end_timestamp}") from exc
    if start_ts and end_ts and start_ts > end_ts:
        raise SystemExit("--start-timestamp must be earlier than or equal to --end-timestamp")
    summary, gap_records, duplicate_records = _audit_internal(
        csv_path,
        args.symbol,
        max_gap_report=max(1, args.max_gap_report),
        max_duplicate_report=max(1, args.max_duplicate_report),
        capture_gap_details=bool(args.out_gap_csv or args.out_gap_json),
        expected_interval_minutes=args.expected_interval_minutes,
        start_timestamp=start_ts,
        end_timestamp=end_ts,
        min_gap_minutes=args.min_gap_minutes,
        min_duplicate_occurrences=args.min_duplicate_occurrences,
        calendar_day_summary=bool(args.calendar_day_summary),
        calendar_day_max_report=max(1, args.calendar_day_max_report),
        calendar_day_coverage_threshold=(
            args.calendar_day_coverage_threshold if args.calendar_day_summary else None
        ),
    )
    failure_reasons: List[str] = []
    fail_under = getattr(args, "fail_under_coverage", None)
    if fail_under is not None:
        coverage_ratio = summary.get("coverage_ratio")
        if coverage_ratio is None:
            failure_reasons.append(
                "coverage ratio unavailable for --fail-under-coverage enforcement"
            )
        elif coverage_ratio < fail_under:
            failure_reasons.append(
                (
                    "coverage_ratio "
                    f"{coverage_ratio:.6f} fell below threshold {fail_under:.6f}"
                )
            )

    if getattr(args, "fail_on_calendar_day_warnings", False):
        calendar_summary = summary.get("calendar_day_summary")
        if not calendar_summary:
            failure_reasons.append(
                "calendar day summary missing despite --fail-on-calendar-day-warnings"
            )
        else:
            warnings = calendar_summary.get("warnings") or []
            if warnings:
                warning_count = len(warnings)
                truncated = calendar_summary.get("warnings_truncated", False)
                if truncated:
                    failure_reasons.append(
                        (
                            f"{warning_count}+ calendar day warnings below coverage threshold "
                            "(truncated)"
                        )
                    )
                else:
                    failure_reasons.append(
                        f"{warning_count} calendar day warnings below coverage threshold"
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
    if getattr(args, "out_gap_json", None):
        out_gap_json_path = Path(args.out_gap_json)
        out_gap_json_path.parent.mkdir(parents=True, exist_ok=True)
        with out_gap_json_path.open("w", encoding="utf-8") as f:
            json.dump(gap_records, f, indent=2, ensure_ascii=False)
    if getattr(args, "out_duplicates_csv", None):
        out_dup_path = Path(args.out_duplicates_csv)
        _write_duplicate_csv(out_dup_path, duplicate_records)
    if getattr(args, "out_duplicates_json", None):
        out_dup_json = Path(args.out_duplicates_json)
        out_dup_json.parent.mkdir(parents=True, exist_ok=True)
        with out_dup_json.open("w", encoding="utf-8") as f:
            json.dump(duplicate_records, f, indent=2, ensure_ascii=False)
    if failure_reasons:
        for reason in failure_reasons:
            print(f"[check_data_quality] FAILURE: {reason}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
