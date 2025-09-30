#!/usr/bin/env python3
"""Utility helpers for fetching bar data from Dukascopy."""
from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, Iterator


def _ensure_module():
    try:
        import dukascopy_python  # type: ignore
        from dukascopy_python import instruments as inst  # type: ignore
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "dukascopy_python is required for Dukascopy ingestion."
        ) from exc
    return dukascopy_python, inst


def _resolve_instrument(symbol: str):
    _, inst = _ensure_module()
    symbol_key = symbol.upper()
    mapping = {
        "USDJPY": inst.INSTRUMENT_FX_MAJORS_USD_JPY,
    }
    if symbol_key not in mapping:
        raise ValueError(f"Unsupported symbol for Dukascopy fetch: {symbol}")
    return mapping[symbol_key]


def _resolve_timeframe(tf: str):
    dukascopy_python, _ = _ensure_module()
    tf_key = tf.lower()
    if tf_key == "5m":
        return 5, dukascopy_python.TIME_UNIT_MIN
    raise ValueError(f"Unsupported timeframe for Dukascopy fetch: {tf}")


def _resolve_offer_side(side: str):
    dukascopy_python, _ = _ensure_module()
    side_key = side.lower()
    if side_key == "bid":
        return dukascopy_python.OFFER_SIDE_BID
    if side_key == "ask":
        return dukascopy_python.OFFER_SIDE_ASK
    raise ValueError(f"Unsupported offer side: {side}")


def _series_get(row, *keys: str) -> float:
    for key in keys:
        if key in row and row[key] == row[key]:
            return float(row[key])
    return 0.0


def fetch_bars(
    symbol: str,
    tf: str,
    *,
    start: datetime,
    end: datetime,
    offer_side: str = "bid",
) -> Iterator[Dict[str, object]]:
    """Yield normalized bar dictionaries from Dukascopy."""

    dukascopy_python, _ = _ensure_module()
    instrument = _resolve_instrument(symbol)
    period, time_unit = _resolve_timeframe(tf)
    offer = _resolve_offer_side(offer_side)

    if end <= start:
        raise ValueError("end must be greater than start")

    iterator = dukascopy_python.live_fetch(
        instrument,
        period,
        time_unit,
        offer,
        start,
        end,
    )

    for frame in iterator:
        if frame is None or frame.empty:
            continue
        for ts, row in frame.sort_index().iterrows():
            dt = ts.to_pydatetime()
            if dt.tzinfo is not None:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            ts_str = dt.strftime("%Y-%m-%dT%H:%M:%S")

            o = _series_get(row, "open", "bid_open", "ask_open")
            h = _series_get(row, "high", "bid_high", "ask_high")
            l = _series_get(row, "low", "bid_low", "ask_low")
            c = _series_get(row, "close", "bid_close", "ask_close")
            v = _series_get(row, "volume")

            yield {
                "timestamp": ts_str,
                "symbol": symbol.upper(),
                "tf": tf,
                "o": o,
                "h": h,
                "l": l,
                "c": c,
                "v": v,
                "spread": 0.0,
            }


def _parse_dt(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc))


def _default_start(end: datetime, *, lookback_minutes: int) -> datetime:
    return end - timedelta(minutes=lookback_minutes)


def _records_to_csv(records: Iterable[Dict[str, object]], writer) -> None:
    header = ["timestamp", "symbol", "tf", "o", "h", "l", "c", "v", "spread"]
    writer.writerow(header)
    for record in records:
        writer.writerow(
            [
                record.get("timestamp", ""),
                record.get("symbol", ""),
                record.get("tf", ""),
                record.get("o", ""),
                record.get("h", ""),
                record.get("l", ""),
                record.get("c", ""),
                record.get("v", ""),
                record.get("spread", ""),
            ]
        )


def _cli(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Fetch bars from Dukascopy")
    parser.add_argument("--symbol", default="USDJPY")
    parser.add_argument("--tf", default="5m")
    parser.add_argument("--start-ts")
    parser.add_argument("--end-ts")
    parser.add_argument("--lookback-minutes", type=int, default=1440)
    parser.add_argument("--offer-side", default="bid", choices=["bid", "ask"])
    parser.add_argument("--out", default="-")
    args = parser.parse_args(argv)

    now = datetime.utcnow()
    end = _parse_dt(args.end_ts) if args.end_ts else now
    start = (
        _parse_dt(args.start_ts)
        if args.start_ts
        else _default_start(end, lookback_minutes=args.lookback_minutes)
    )

    records = list(
        fetch_bars(
            args.symbol,
            args.tf,
            start=start,
            end=end,
            offer_side=args.offer_side,
        )
    )

    if args.out == "-":
        writer = csv.writer(sys.stdout)
        _records_to_csv(records, writer)
    else:
        with open(args.out, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            _records_to_csv(records, writer)
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(_cli())
