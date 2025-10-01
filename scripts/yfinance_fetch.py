#!/usr/bin/env python3
"""Helper to download bars from yfinance for ingestion."""
from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, Iterator

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


def _ensure_module():
    try:
        import yfinance as yf  # type: ignore
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("yfinance is required for yfinance ingestion") from exc
    return yf


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


def _normalize_index_ts(value) -> datetime:
    if hasattr(value, "to_pydatetime"):
        dt = value.to_pydatetime()
    else:
        dt = datetime.fromtimestamp(float(value))
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    else:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.replace(tzinfo=None)


def _safe_float(value) -> float:
    try:
        result = float(value)
    except Exception:
        return 0.0
    if result != result:  # NaN check
        return 0.0
    return result


def fetch_bars(
    symbol: str,
    tf: str,
    *,
    start: datetime,
    end: datetime,
    auto_adjust: bool = False,
) -> Iterator[Dict[str, object]]:
    """Yield normalized OHLCV rows fetched from yfinance."""

    interval = _INTERVAL_MAP.get(tf)
    if interval is None:
        raise ValueError(f"Unsupported timeframe for yfinance fetch: {tf}")

    now_utc = datetime.utcnow()
    yf = _ensure_module()
    ticker = _resolve_ticker(symbol)

    download_kwargs = {
        "tickers": ticker,
        "interval": interval,
        "auto_adjust": auto_adjust,
        "progress": False,
        "repair": True,
    }

    if interval.endswith("m"):
        period_start = now_utc - timedelta(days=7)
        download_kwargs["period"] = "7d"
    else:
        period_start = start
        download_kwargs["start"] = start
        download_kwargs["end"] = min(end, now_utc)

    frame = yf.download(**download_kwargs)

    if frame is None:
        return iter(())

    try:
        frame = frame.dropna(how="all")
    except AttributeError:
        return iter(())

    if getattr(frame, "empty", True):
        return iter(())

    if getattr(frame.columns, "nlevels", 1) > 1:
        try:
            frame = frame.xs(ticker, axis=1, level=-1)
        except Exception:
            try:
                frame = frame.droplevel(-1, axis=1)  # type: ignore[attr-defined]
            except Exception:
                pass

    target_start = max(start, period_start)
    target_end = min(end, now_utc)
    if target_end <= target_start:
        return iter(())

    def _iter() -> Iterator[Dict[str, object]]:
        for ts, row in frame.iterrows():
            dt = _normalize_index_ts(ts)
            if dt < target_start or dt > target_end:
                continue

            open_px = _safe_float(row.get("Open", row.get("open")))
            high_px = _safe_float(row.get("High", row.get("high")))
            low_px = _safe_float(row.get("Low", row.get("low")))
            close_px = _safe_float(row.get("Close", row.get("close")))
            volume = _safe_float(row.get("Volume", row.get("volume")))

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
    parser.add_argument("--auto-adjust", action="store_true")
    parser.add_argument("--out", default="-")
    args = parser.parse_args(argv)

    now = datetime.utcnow()
    end = datetime.fromisoformat(args.end_ts) if args.end_ts else now
    start = datetime.fromisoformat(args.start_ts) if args.start_ts else end - timedelta(days=1)

    records = list(
        fetch_bars(
            args.symbol,
            args.tf,
            start=start,
            end=end,
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
