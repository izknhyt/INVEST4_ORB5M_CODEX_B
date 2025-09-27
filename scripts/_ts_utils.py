"""Shared helpers for timestamp parsing in operational scripts."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence


def _normalize_iso_string(value: str) -> str:
    """Normalize timestamp string for ``datetime.fromisoformat``.

    Currently handles the common case where providers emit ``Z`` suffix to
    indicate UTC. ``datetime.fromisoformat`` does not accept that shorthand, so
    we replace it with ``+00:00``.
    """
    normalized = value
    if normalized.endswith(("Z", "z")):
        normalized = normalized[:-1] + "+00:00"
    return normalized


def parse_naive_utc_timestamp(value: str, *, fallback_formats: Sequence[str] | None = None) -> datetime:
    """Parse ``value`` into a naive ``datetime`` in UTC.

    The helper mirrors the various timestamp formats encountered across ingest
    and benchmark scripts:

    - ISO 8601 strings with ``T`` or space separators
    - Values with ``Z`` suffix or explicit offsets such as ``+09:00``
    - Optional fallback ``strptime`` formats (e.g. legacy CSV exports)

    Args:
        value: Raw timestamp string from CSV/API sources.
        fallback_formats: Additional ``strptime`` formats to try when
            ``datetime.fromisoformat`` fails.

    Returns:
        ``datetime`` without ``tzinfo`` in UTC.

    Raises:
        ValueError: If the value is empty or cannot be parsed.
    """

    text = value.strip()
    if not text:
        raise ValueError("empty timestamp")

    normalized = _normalize_iso_string(text)
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError as exc:
        if fallback_formats:
            for fmt in fallback_formats:
                try:
                    return datetime.strptime(text, fmt)
                except ValueError:
                    continue
        raise ValueError(f"invalid timestamp: {value!r}") from exc

    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt
