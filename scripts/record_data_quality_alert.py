#!/usr/bin/env python3
"""Append acknowledgement entries to the data-quality alert log."""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOG = ROOT / "ops/health/data_quality_alerts.md"
ALLOWED_STATUS = {"investigating", "backfill-running", "resolved", "escalated"}


def _utcnow_iso() -> str:
    """Return the current UTC timestamp in ISO8601 (seconds, Z suffix)."""

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _parse_iso8601(value: str) -> str:
    """Parse ``value`` into an ISO8601 string normalised to UTC."""

    text = (value or "").strip()
    if not text:
        raise argparse.ArgumentTypeError("Timestamp value cannot be empty")

    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid ISO8601 timestamp: {value!r}"
        ) from exc

    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError(
            "Timestamp must include a timezone offset or 'Z' suffix"
        )

    normalised = parsed.astimezone(timezone.utc).replace(microsecond=0)
    return normalised.isoformat().replace("+00:00", "Z")


def _parse_coverage_ratio(value: str) -> float:
    """Parse and validate a coverage ratio within the inclusive [0, 1] range."""

    text = (value or "").strip()
    if not text:
        raise argparse.ArgumentTypeError("Coverage ratio cannot be empty")

    try:
        ratio = float(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Coverage ratio must be numeric: {value!r}"
        ) from exc

    if not 0.0 <= ratio <= 1.0:
        raise argparse.ArgumentTypeError(
            "Coverage ratio must be between 0 and 1 inclusive"
        )

    return ratio


def _sanitize_cell(value: str) -> str:
    """Normalise table cell contents for Markdown rendering.

    - Collapse leading/trailing whitespace.
    - Replace internal newlines with `<br>` so multi-line notes remain readable.
    - Escape vertical bars to avoid breaking the table layout.
    """

    text = value.strip()
    text = text.replace("\n", "<br>")
    text = text.replace("|", "&#124;")
    return text


@dataclass
class AlertRow:
    alert_timestamp: str
    symbol: str
    timeframe: str
    coverage_ratio: float
    ack_by: str
    ack_timestamp: str
    status: str
    remediation: str
    follow_up: str

    def to_markdown(self) -> str:
        def fmt(value: str) -> str:
            return _sanitize_cell(value)

        coverage = f"{self.coverage_ratio:.4f}"
        cells = (
            fmt(self.alert_timestamp),
            fmt(self.symbol.upper()),
            fmt(self.timeframe),
            fmt(coverage),
            fmt(self.ack_by),
            fmt(self.ack_timestamp),
            fmt(self.status),
            fmt(self.remediation),
            fmt(self.follow_up),
        )
        return "| " + " | ".join(cells) + " |"


def _ensure_log_exists(path: Path) -> None:
    """Create the acknowledgement log with headers when missing."""

    if path.exists():
        return

    header_lines = [
        "# Data Quality Alert Acknowledgements",
        "",
        "| alert_timestamp (UTC) | symbol | tf | coverage_ratio | ack_by | ack_timestamp (UTC) | status | remediation | follow_up |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        "",
        "> Status values: `investigating`, `backfill-running`, `resolved`, `escalated`.",
        "",
        "Link remediation commands (e.g. rerunning `scripts/check_data_quality.py`",
        "or invoking ingest fallbacks) directly in the table so reviewers can",
        "trace the action history.",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(header_lines), encoding="utf-8")


def _load_lines(path: Path) -> List[str]:
    return path.read_text(encoding="utf-8").splitlines()


def _extract_acknowledgement_keys(lines: Iterable[str]) -> set[tuple[str, str, str]]:
    """Return the set of existing acknowledgement identity tuples."""

    keys: set[tuple[str, str, str]] = set()
    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped.startswith("|"):
            continue
        if stripped.startswith("| ---"):
            continue
        cells = [cell.strip() for cell in stripped.split("|")[1:-1]]
        if len(cells) < 3:
            continue
        header = cells[0].lower()
        if header.startswith("alert_timestamp"):
            continue
        alert_ts, symbol, timeframe = cells[0], cells[1], cells[2]
        keys.add((alert_ts, symbol.upper(), timeframe))
    return keys


def _insert_row(lines: Iterable[str], row: str) -> List[str]:
    """Insert *row* immediately after the table header separator."""

    result = list(lines)
    try:
        header_idx = next(
            idx
            for idx, line in enumerate(result)
            if line.strip().startswith("| alert_timestamp")
        )
        separator_idx = header_idx + 1
        while separator_idx < len(result) and not result[separator_idx].strip().startswith(
            "| ---"
        ):
            separator_idx += 1
    except StopIteration as exc:  # pragma: no cover - defensive guard
        raise RuntimeError("Acknowledgement log is missing the Markdown table header") from exc

    if separator_idx >= len(result):  # pragma: no cover - defensive guard
        raise RuntimeError("Acknowledgement log is missing the Markdown header separator")

    insert_at = separator_idx + 1
    result.insert(insert_at, row)
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Append a data-quality acknowledgement row to the shared log"
    )
    parser.add_argument(
        "--alert-timestamp",
        required=True,
        type=_parse_iso8601,
        help="Alert generated_at timestamp (UTC, ISO8601 with timezone)",
    )
    parser.add_argument("--symbol", required=True, help="Symbol reported by the alert")
    parser.add_argument("--timeframe", "--tf", default="5m", help="Timeframe token (default: 5m)")
    parser.add_argument(
        "--coverage-ratio",
        required=True,
        type=_parse_coverage_ratio,
        help="Coverage ratio conveyed by the alert payload (0-1)",
    )
    parser.add_argument("--ack-by", required=True, help="Responder acknowledging the alert")
    parser.add_argument(
        "--ack-timestamp",
        default=None,
        type=_parse_iso8601,
        help="UTC timestamp of the acknowledgement (defaults to current UTC time)",
    )
    parser.add_argument(
        "--status",
        required=True,
        choices=sorted(ALLOWED_STATUS),
        help="Operational status recorded in the log",
    )
    parser.add_argument(
        "--remediation",
        default="",
        help="Summary of remediation commands or notes (Markdown supported)",
    )
    parser.add_argument(
        "--follow-up",
        default="",
        help="Links or ticket references for follow-up actions",
    )
    parser.add_argument(
        "--log-path",
        default=str(DEFAULT_LOG),
        help="Path to ops/health/data_quality_alerts.md",
    )
    parser.add_argument(
        "--allow-duplicate",
        action="store_true",
        help="Permit appending a row even when an acknowledgement for the same alert already exists",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print the row without writing the log")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    ack_timestamp = args.ack_timestamp or _utcnow_iso()

    row = AlertRow(
        alert_timestamp=args.alert_timestamp,
        symbol=args.symbol,
        timeframe=args.timeframe,
        coverage_ratio=args.coverage_ratio,
        ack_by=args.ack_by,
        ack_timestamp=ack_timestamp,
        status=args.status,
        remediation=args.remediation,
        follow_up=args.follow_up,
    )
    markdown_row = row.to_markdown()

    if args.dry_run:
        print(markdown_row)
        return 0

    log_path = Path(args.log_path)
    _ensure_log_exists(log_path)
    lines = _load_lines(log_path)
    existing_keys = _extract_acknowledgement_keys(lines)
    ack_key = (row.alert_timestamp, row.symbol.upper(), row.timeframe)
    if ack_key in existing_keys and not args.allow_duplicate:
        key_text = "alert_timestamp={0} symbol={1} timeframe={2}".format(*ack_key)
        print(
            "Duplicate acknowledgement detected for {key}; pass --allow-duplicate to append anyway.".format(
                key=key_text
            ),
            file=sys.stderr,
        )
        return 1
    updated = _insert_row(lines, markdown_row)
    log_path.write_text("\n".join(updated) + "\n", encoding="utf-8")
    print(f"Appended acknowledgement row to {log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
