#!/usr/bin/env python3
"""Helper to download bars from Yahoo Finance for ingestion."""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, Iterator, List, Optional, Tuple

_INTERVAL_MAP = {
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "60m",
    "1d": "1d",
}

_SYMBOL_OVERRIDES = {
    "USDJPY": "JPY=X",
}

_BASE_URL = "https://query1.finance.yahoo.com/v8/finance/chart"
_DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}
_REQUEST_TIMEOUT = 15
_INTRADAY_WINDOW_DAYS = 7
_INTRADAY_HISTORY_LIMIT_DAYS = 60


def _resolve_ticker(symbol: str) -> str:
    upper = symbol.upper()
    if upper in _SYMBOL_OVERRIDES:
        return _SYMBOL_OVERRIDES[upper]
    if "=" in upper:
        return upper
    if len(upper) == 6 and upper.isalpha():
        return f"{upper}=X"
    return upper


def resolve_ticker(symbol: str) -> str:
    """Return the Yahoo Finance ticker used for the provided symbol."""

    return _resolve_ticker(symbol)


def _to_naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _epoch_seconds(value: datetime) -> int:
    value_utc = value.replace(tzinfo=timezone.utc)
    return int(value_utc.timestamp())


def _safe_float(value) -> Optional[float]:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(result) or math.isinf(result):
        return None
    return result


def _value_at(values: Optional[List[object]], index: int) -> Optional[object]:
    if not values:
        return None
    try:
        return values[index]
    except (IndexError, TypeError):
        return None


def _download_chart_json(
    ticker: str,
    interval: str,
    start: datetime,
    end: datetime,
) -> Dict[str, object]:
    params = {
        "interval": interval,
        "period1": str(_epoch_seconds(start)),
        "period2": str(_epoch_seconds(end)),
        "includePrePost": "false",
        "events": "history",
    }
    url = f"{_BASE_URL}/{urllib.parse.quote(ticker)}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers=_DEFAULT_HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:  # pragma: no cover - network failure
        raise RuntimeError(f"yahoo_http_error:{exc.code}") from exc
    except urllib.error.URLError as exc:  # pragma: no cover - network failure
        raise RuntimeError(f"yahoo_network_error:{exc.reason}") from exc

    try:
        return json.loads(payload.decode("utf-8"))
    except Exception as exc:  # pragma: no cover - invalid JSON
        raise RuntimeError("yahoo_invalid_response") from exc


def _iter_quote_rows(
    data: Dict[str, object],
    *,
    symbol: str,
    tf: str,
    start: datetime,
    end: datetime,
    auto_adjust: bool,
    min_timestamp: Optional[datetime] = None,
) -> Iterator[Dict[str, object]]:
    chart = data.get("chart", {}) if isinstance(data, dict) else {}
    error = chart.get("error") if isinstance(chart, dict) else None
    if error:
        raise RuntimeError(f"yahoo_chart_error:{error}")

    results = chart.get("result") if isinstance(chart, dict) else None
    if not results:
        return iter(())

    payload = results[0]
    if not isinstance(payload, dict):
        return iter(())

    timestamps = payload.get("timestamp") or []
    indicators = payload.get("indicators") or {}
    quote_entries = indicators.get("quote") if isinstance(indicators, dict) else None
    if not quote_entries:
        return iter(())

    quote = quote_entries[0] if isinstance(quote_entries, list) else None
    if not isinstance(quote, dict):
        return iter(())

    adjclose_list: Optional[List[object]] = None
    if auto_adjust:
        adj_entries = indicators.get("adjclose") if isinstance(indicators, dict) else None
        if isinstance(adj_entries, list) and adj_entries:
            adj_payload = adj_entries[0]
            if isinstance(adj_payload, dict):
                adj_values = adj_payload.get("adjclose")
                if isinstance(adj_values, list):
                    adjclose_list = adj_values

    def _generator() -> Iterator[Dict[str, object]]:
        last_dt: Optional[datetime] = min_timestamp
        for index, ts in enumerate(timestamps):
            ts_value = _safe_float(ts)
            if ts_value is None:
                continue

            dt = datetime.fromtimestamp(ts_value, tz=timezone.utc).replace(tzinfo=None)
            if dt < start or dt > end:
                continue
            if last_dt is not None and dt <= last_dt:
                continue
            last_dt = dt

            open_px = _safe_float(_value_at(quote.get("open"), index))
            high_px = _safe_float(_value_at(quote.get("high"), index))
            low_px = _safe_float(_value_at(quote.get("low"), index))
            close_px = _safe_float(_value_at(quote.get("close"), index))
            volume = _safe_float(_value_at(quote.get("volume"), index))

            if None in (open_px, high_px, low_px, close_px):
                continue

            if auto_adjust and adjclose_list is not None:
                adj_close = _safe_float(_value_at(adjclose_list, index))
                if adj_close is not None and close_px not in (None, 0.0):
                    if close_px != 0.0:
                        ratio = adj_close / close_px
                        open_px *= ratio
                        high_px *= ratio
                        low_px *= ratio
                    close_px = adj_close

            yield {
                "timestamp": dt.strftime("%Y-%m-%dT%H:%M:%S"),
                "symbol": symbol.upper(),
                "tf": tf,
                "o": open_px,
                "h": high_px,
                "l": low_px,
                "c": close_px,
                "v": volume or 0.0,
                "spread": 0.0,
            }

    return _generator()


def fetch_bars(
    symbol: str,
    tf: str,
    *,
    start: datetime,
    end: datetime,
    auto_adjust: bool = False,
) -> Iterator[Dict[str, object]]:
    """Yield normalized OHLCV rows fetched from Yahoo Finance."""

    interval = _INTERVAL_MAP.get(tf)
    if interval is None:
        raise ValueError(f"Unsupported timeframe for yfinance fetch: {tf}")

    now_utc = datetime.utcnow()
    ticker = _resolve_ticker(symbol)

    start_naive = _to_naive_utc(start)
    end_naive = _to_naive_utc(end)
    end_clamped = min(end_naive, now_utc)
    if end_clamped <= start_naive:
        return iter(())

    if interval.endswith("m"):
        history_start = max(
            start_naive,
            end_clamped - timedelta(days=_INTRADAY_HISTORY_LIMIT_DAYS),
        )
        if history_start >= end_clamped:
            return iter(())

        windows: Iterable[Tuple[datetime, datetime]] = _iter_intraday_windows(
            history_start,
            end_clamped,
        )
    else:
        windows = ((start_naive, end_clamped),)

    def _generate() -> Iterator[Dict[str, object]]:
        last_timestamp: Optional[datetime] = None
        for window_start, window_end in windows:
            payload = _download_chart_json(ticker, interval, window_start, window_end)
            rows = list(
                _iter_quote_rows(
                    payload,
                    symbol=symbol,
                    tf=tf,
                    start=start_naive,
                    end=end_clamped,
                    auto_adjust=auto_adjust,
                    min_timestamp=last_timestamp,
                )
            )
            if not rows:
                continue
            for row in rows:
                yield row
            last_timestamp = datetime.strptime(
                rows[-1]["timestamp"], "%Y-%m-%dT%H:%M:%S"
            )

    return _generate()


def _iter_intraday_windows(
    start: datetime,
    end: datetime,
) -> Iterator[Tuple[datetime, datetime]]:
    cursor = start
    max_delta = timedelta(days=_INTRADAY_WINDOW_DAYS)
    while cursor < end:
        window_end = min(cursor + max_delta, end)
        yield cursor, window_end
        cursor = window_end + timedelta(seconds=1)


def _records_to_csv(records: Iterable[Dict[str, object]], writer) -> None:
    header = ["timestamp", "symbol", "tf", "o", "h", "l", "c", "v", "spread"]
    writer.writerow(header)
    for row in records:
        writer.writerow([row.get(col, "") for col in header])


def _cli(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Fetch bars from Yahoo Finance")
    parser.add_argument("--symbol", default="USDJPY")
    parser.add_argument("--tf", default="5m")
    parser.add_argument("--start-ts")
    parser.add_argument("--end-ts")
    parser.add_argument("--auto-adjust", action="store_true")
    parser.add_argument("--out", default="-")
    args = parser.parse_args(argv)

    now = datetime.utcnow()
    end_dt = datetime.fromisoformat(args.end_ts) if args.end_ts else now
    start_dt = (
        datetime.fromisoformat(args.start_ts)
        if args.start_ts
        else end_dt - timedelta(days=1)
    )

    records = list(
        fetch_bars(
            args.symbol,
            args.tf,
            start=start_dt,
            end=end_dt,
            auto_adjust=args.auto_adjust,
        )
    )

    if args.out == "-":
        writer = csv.writer(sys.stdout)
        _records_to_csv(records, writer)
    else:
        with open(args.out, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            _records_to_csv(records, writer)
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(_cli(sys.argv[1:]))
