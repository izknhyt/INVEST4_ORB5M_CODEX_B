"""Shared helpers for ingestion providers and fallbacks."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import partial
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple


__all__ = [
    "ProviderError",
    "parse_naive_utc",
    "load_dukascopy_fetch",
    "resolve_dukascopy_fetch",
    "fetch_dukascopy_records",
    "compute_yfinance_fallback_start",
    "load_yfinance_module",
    "fetch_yfinance_records",
    "raise_provider_error",
    "mark_dukascopy_offer_side",
    "YFinanceFallbackRunner",
]


class ProviderError(RuntimeError):
    """Error type carrying a preformatted reason string for provider failures."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def parse_naive_utc(timestamp: str) -> Optional[datetime]:
    """Parse ISO 8601 timestamps into naive UTC datetimes."""

    if not timestamp:
        return None

    value = timestamp.strip()
    if not value:
        return None

    if value.endswith("Z"):
        value = value[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None

    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)

    return parsed


def load_dukascopy_fetch() -> Callable[..., Iterable[Dict[str, object]]]:
    """Return the Dukascopy fetch function, raising if unavailable."""

    from scripts.dukascopy_fetch import fetch_bars

    return fetch_bars


def resolve_dukascopy_fetch() -> Tuple[Optional[Callable[..., object]], Optional[Exception]]:
    """Return the Dukascopy fetch implementation and any initialization error."""

    try:
        return load_dukascopy_fetch(), None
    except Exception as exc:  # pragma: no cover - optional dependency
        return None, exc


def fetch_dukascopy_records(
    fetch_impl: Optional[Callable[..., Iterable[Dict[str, object]]]],
    symbol: str,
    tf: str,
    *,
    start: datetime,
    end: datetime,
    offer_side: str,
    init_error: Optional[Exception],
    freshness_threshold: Optional[int],
    timestamp_parser: Callable[[str], Optional[datetime]] = parse_naive_utc,
) -> List[Dict[str, object]]:
    """Fetch Dukascopy records and validate freshness."""

    if fetch_impl is None:
        raise ProviderError(f"initialization error: {init_error}")

    records = list(
        fetch_impl(
            symbol,
            tf,
            start=start,
            end=end,
            offer_side=offer_side,
        )
    )

    if not records:
        raise ProviderError("no rows returned")

    last_record_ts = str(records[-1].get("timestamp", ""))
    parsed_last = timestamp_parser(last_record_ts)
    if parsed_last is None:
        raise ProviderError("could not parse last timestamp")

    if freshness_threshold and freshness_threshold > 0:
        max_age = timedelta(minutes=freshness_threshold)
        if end - parsed_last > max_age:
            raise ProviderError(
                "stale data: "
                f"last_ts={parsed_last.isoformat(timespec='seconds')}"
            )

    return records


def compute_yfinance_fallback_start(
    *,
    last_ts: Optional[datetime],
    lookback_minutes: Optional[int],
    now: datetime,
    fallback_window_days: int = 7,
) -> datetime:
    """Return the fallback start time for yfinance ingestion."""

    fallback_window = timedelta(days=fallback_window_days)
    yf_lookback_minutes = max(5, lookback_minutes or 0)
    if last_ts is not None:
        fallback_start = last_ts - timedelta(minutes=yf_lookback_minutes)
    else:
        minutes = max(yf_lookback_minutes, fallback_window_days * 24 * 60)
        fallback_start = now - timedelta(minutes=minutes)
    fallback_start = max(fallback_start, now - fallback_window)
    if fallback_start > now:
        return now
    return fallback_start


def load_yfinance_module():
    """Import and return the yfinance adapter module."""

    from scripts import yfinance_fetch as yfinance_module

    return yfinance_module


def fetch_yfinance_records(
    fetch_bars: Callable[..., Iterable[Dict[str, object]]],
    symbol: str,
    tf: str,
    *,
    start: datetime,
    end: datetime,
    empty_reason: str,
) -> List[Dict[str, object]]:
    """Fetch yfinance records and ensure the response is non-empty."""

    records = list(
        fetch_bars(
            symbol,
            tf,
            start=start,
            end=end,
        )
    )
    if not records:
        raise ProviderError(empty_reason)
    return records


def raise_provider_error(message: str) -> Iterable[Dict[str, object]]:
    """Helper that raises a ``ProviderError`` when invoked by ingest wrappers."""

    raise ProviderError(message)


def mark_dukascopy_offer_side(
    result_dict: Dict[str, object],
    *,
    offer_side: str,
) -> None:
    """Annotate ingest result metadata with the Dukascopy offer side when applicable."""

    source_markers: List[str] = ["dukascopy"]
    source_value = result_dict.get("source")
    if source_value:
        source_markers.append(str(source_value))
    normalized = [marker.lower() for marker in source_markers if marker]
    if any("dukascopy" in marker for marker in normalized):
        result_dict.setdefault("dukascopy_offer_side", offer_side)


class YFinanceFallbackRunner:
    """Callable wrapper that executes the yfinance fallback ingest flow."""

    def __init__(
        self,
        ctx: Any,
        args: Any,
        *,
        now: datetime,
        last_ts: Optional[datetime],
        ingest_runner: Callable[..., Tuple[Optional[Dict[str, object]], Optional[str]]],
        yfinance_loader: Optional[Callable[[], Any]] = None,
    ) -> None:
        self._ctx = ctx
        self._args = args
        self._now = now
        self._last_ts = last_ts
        self._ingest_runner = ingest_runner
        self._yfinance_loader = yfinance_loader or load_yfinance_module

    def __call__(self, reason: str) -> Tuple[Optional[Dict[str, object]], Optional[str]]:
        print(
            "[wf] Dukascopy unavailable, switching to yfinance fallback:",
            reason,
        )

        try:
            yfinance_module = self._yfinance_loader()
        except Exception as exc:  # pragma: no cover - optional dependency
            fetch_callable = partial(
                raise_provider_error,
                f"yfinance import failed: {exc}",
            )
            return self._ingest_runner(
                stage="yfinance",
                source_label="yfinance",
                next_source="local_csv",
                fetch_records=fetch_callable,
                fetch_error_prefix="yfinance ingestion failed",
                empty_result_reason="yfinance ingestion returned no rows",
                ingest_error_prefix="yfinance ingestion failed during ingest",
            )

        fallback_start = compute_yfinance_fallback_start(
            last_ts=self._last_ts,
            lookback_minutes=self._args.yfinance_lookback_minutes,
            now=self._now,
        )

        fetch_symbol = yfinance_module.resolve_ticker(self._ctx.symbol)
        print(
            "[wf] fetching yfinance bars",
            fetch_symbol,
            f"(fallback for {self._ctx.symbol})",
            self._ctx.tf,
            fallback_start.isoformat(timespec="seconds"),
            self._now.isoformat(timespec="seconds"),
        )

        fetch_callable = partial(
            fetch_yfinance_records,
            yfinance_module.fetch_bars,
            self._args.symbol,
            self._ctx.tf,
            start=fallback_start,
            end=self._now,
            empty_reason="yfinance fallback returned no rows",
        )

        return self._ingest_runner(
            stage="yfinance",
            source_label="yfinance",
            next_source="local_csv",
            fetch_records=fetch_callable,
            fetch_error_prefix="yfinance ingestion failed",
            empty_result_reason="yfinance ingestion returned no rows",
            ingest_error_prefix="yfinance ingestion failed during ingest",
        )

