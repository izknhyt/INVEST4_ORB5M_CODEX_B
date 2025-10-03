#!/usr/bin/env python3
"""Helper to download bars from yfinance for ingestion without heavy deps."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, Iterator, List, Optional

from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from scripts._time_utils import utcnow_naive


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

_YF_BASE_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
_YF_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; invest3-orb5m/1.0)",
    "Accept": "application/json",
}


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


def _safe_float(value) -> float:
    try:
        result = float(value)
    except Exception:
        return 0.0
    if result != result:  # NaN check
        return 0.0
    return result


def _to_datetime(epoch_seconds: int) -> datetime:
    dt = datetime.fromtimestamp(int(epoch_seconds), tz=timezone.utc)
    return dt.replace(second=0, microsecond=0, tzinfo=None)


def _download_chart(
    *,
    ticker: str,
    interval: str,
    start: datetime,
    end: datetime,
) -> Dict[str, object]:
    params = {
        "interval": interval,
        "period1": int(start.replace(tzinfo=timezone.utc).timestamp()),
        "period2": int(end.replace(tzinfo=timezone.utc).timestamp()),
        "includePrePost": "true",
        "events": "div,splits",
    }

    url = _YF_BASE_URL.format(ticker=ticker)
    query = urlencode(params)
    request = Request(f"{url}?{query}", headers=_YF_HEADERS)

    try:
        with urlopen(request, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
    except HTTPError as exc:  # pragma: no cover - network error path
        raise RuntimeError(f"yfinance HTTP error: {exc.code}") from exc
    except URLError as exc:  # pragma: no cover - network error path
        raise RuntimeError(f"yfinance connection error: {exc.reason}") from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("yfinance JSON decode error") from exc

    chart = payload.get("chart", {})
    if chart.get("error"):
        raise RuntimeError(f"yfinance returned error: {chart['error']}")

    results: Optional[List[Dict[str, object]]] = chart.get("result")
    if not results:
        return {}

    return results[0]


def fetch_bars(
    symbol: str,
    tf: str,
    *,
    start: datetime,
    end: datetime,
) -> Iterator[Dict[str, object]]:
    """Yield normalized OHLCV rows fetched from yfinance."""

    interval = _INTERVAL_MAP.get(tf)
    if interval is None:
        raise ValueError(f"Unsupported timeframe for yfinance fetch: {tf}")

    now_utc = utcnow_naive(dt_cls=datetime)
    ticker = _resolve_ticker(symbol)

    effective_start = start.replace(tzinfo=timezone.utc)
    effective_end = min(end, now_utc).replace(tzinfo=timezone.utc)
    if effective_end <= effective_start:
        return iter(())

    try:
        chart = _download_chart(
            ticker=ticker,
            interval=interval,
            start=effective_start,
            end=effective_end,
        )
    except Exception:
        return iter(())

    timestamps: Optional[List[int]] = chart.get("timestamp") if chart else None
    indicators: Optional[Dict[str, List[Dict[str, object]]]] = chart.get("indicators") if chart else None

    if not timestamps or not indicators:
        return iter(())

    quotes: Optional[List[Dict[str, Iterable[float]]]] = indicators.get("quote") if indicators else None
    if not quotes:
        return iter(())

    quote = quotes[0]
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []

    target_start = start.replace(tzinfo=None)
    target_end = min(end, now_utc).replace(tzinfo=None)

    def _iter() -> Iterator[Dict[str, object]]:
        for idx, ts in enumerate(timestamps):
            dt = _to_datetime(ts)
            if dt < target_start or dt > target_end:
                continue

            open_px = _safe_float(opens[idx] if idx < len(opens) else 0.0)
            high_px = _safe_float(highs[idx] if idx < len(highs) else 0.0)
            low_px = _safe_float(lows[idx] if idx < len(lows) else 0.0)
            close_px = _safe_float(closes[idx] if idx < len(closes) else 0.0)
            volume = _safe_float(volumes[idx] if idx < len(volumes) else 0.0)

            if not all([open_px, high_px, low_px, close_px]):
                continue

            yield {
                "timestamp": dt.strftime("%Y-%m-%dT%H:%M:%S"),
                "symbol": symbol.upper(),
                "tf": tf,
                "o": open_px,
                "h": high_px,
                "l": low_px,
                "c": close_px,
                "v": volume,
                "spread": 0.0,
            }

    return _iter()


def _records_to_csv(records: Iterable[Dict[str, object]], writer) -> None:
    header = ["timestamp", "symbol", "tf", "o", "h", "l", "c", "v", "spread"]
    writer.writerow(header)
    for row in records:
        writer.writerow([row.get(col, "") for col in header])


def _cli(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Fetch bars from yfinance")
    parser.add_argument("--symbol", default="USDJPY")
    parser.add_argument("--tf", default="5m")
    parser.add_argument("--start-ts")
    parser.add_argument("--end-ts")
    parser.add_argument("--out", default="-")
    args = parser.parse_args(argv)

    now = utcnow_naive(dt_cls=datetime)
    end = datetime.fromisoformat(args.end_ts) if args.end_ts else now
    start = datetime.fromisoformat(args.start_ts) if args.start_ts else end - timedelta(days=1)

    records = list(
        fetch_bars(
            args.symbol,
            args.tf,
            start=start,
            end=end,
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
    raise SystemExit(_cli())
