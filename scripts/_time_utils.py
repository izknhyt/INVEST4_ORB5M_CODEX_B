"""Shared helpers for UTC timestamp handling with monkeypatch-friendly fallbacks."""
from __future__ import annotations

from datetime import datetime as _datetime, timezone
from typing import Optional

# Allow monkeypatching via ``scripts._time_utils.datetime``
datetime = _datetime  # type: ignore


def _coerce_aware(value: _datetime) -> _datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _resolve_from_class(dt_cls) -> Optional[_datetime]:
    if dt_cls is _datetime:
        return _coerce_aware(_datetime.now(timezone.utc))

    utcnow_method = getattr(dt_cls, "utcnow", None)
    if callable(utcnow_method):
        current = utcnow_method()
        if hasattr(current, "tzinfo"):
            return _coerce_aware(current)  # type: ignore[arg-type]
        if isinstance(current, _datetime):
            return _coerce_aware(current)

    now_method = getattr(dt_cls, "now", None)
    if callable(now_method):
        try:
            current = now_method(timezone.utc)
        except TypeError:
            current = now_method()
        if hasattr(current, "tzinfo"):
            return _coerce_aware(current)  # type: ignore[arg-type]
        if isinstance(current, _datetime):
            return _coerce_aware(current)
    return None


def utcnow_aware(dt_cls=None) -> _datetime:
    """Return the current UTC time as a timezone-aware ``datetime``."""

    candidate_cls = dt_cls or datetime
    resolved = _resolve_from_class(candidate_cls)
    if resolved is not None:
        return resolved
    return _coerce_aware(_datetime.now(timezone.utc))


def utcnow_naive(dt_cls=None) -> _datetime:
    """Return the current UTC time as a naive ``datetime``."""

    return utcnow_aware(dt_cls=dt_cls).replace(tzinfo=None)


def utcnow_iso(dt_cls=None) -> str:
    """Return the current UTC time as an ISO8601 string with ``Z`` suffix."""

    return (
        utcnow_aware(dt_cls=dt_cls)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
