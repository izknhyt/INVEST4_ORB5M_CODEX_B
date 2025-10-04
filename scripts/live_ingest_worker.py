#!/usr/bin/env python3
"""Daemon-style live ingestion worker for Dukascopy with fallback."""
from __future__ import annotations

import argparse
import signal
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from scripts import ingest_providers  # noqa: E402  # isort:skip
from scripts._time_utils import (  # noqa: E402  # isort:skip
    parse_naive_utc,
    utcnow_naive,
)
from scripts.pull_prices import (  # noqa: E402  # isort:skip
    FEATURES_ROOT,
    RAW_ROOT,
    SNAPSHOT_PATH,
    VALIDATED_ROOT,
    get_last_processed_ts,
    ingest_records,
)


@dataclass
class WorkerConfig:
    symbols: Sequence[str]
    modes: Sequence[str]
    tf: str
    interval: float
    lookback_minutes: int
    freshness_threshold: Optional[int]
    offer_side: str
    snapshot_path: Path
    raw_root: Path
    validated_root: Path
    features_root: Path
    shutdown_file: Optional[Path]
    max_iterations: Optional[int]
    or_n: int


class StopSignal:
    def __init__(self) -> None:
        self._stop = False

    def request(self) -> None:
        self._stop = True

    @property
    def requested(self) -> bool:
        return self._stop


def _parse_csv_list(
    value: Optional[str], *, default: Sequence[str], case: Optional[str] = "upper"
) -> List[str]:
    def _apply_case(items: Sequence[str]) -> List[str]:
        if case == "upper":
            return [item.upper() for item in items]
        if case == "lower":
            return [item.lower() for item in items]
        return [str(item) for item in items]

    if not value:
        return _apply_case(default)
    items = []
    for part in value.split(","):
        item = part.strip()
        if not item:
            continue
        items.append(item)
    if not items:
        return _apply_case(default)
    return _apply_case(items)


_parse_timestamp = parse_naive_utc


def _load_dukascopy_records(
    symbol: str,
    tf: str,
    *,
    start: datetime,
    end: datetime,
    offer_side: str,
    freshness_threshold: Optional[int],
) -> List[dict]:
    fetch_impl, init_error = ingest_providers.resolve_dukascopy_fetch()

    return ingest_providers.fetch_dukascopy_records(
        fetch_impl,
        symbol,
        tf,
        start=start,
        end=end,
        offer_side=offer_side,
        init_error=init_error,
        freshness_threshold=freshness_threshold,
    )


def _load_yfinance_records(symbol: str, tf: str, start: datetime, end: datetime) -> List[dict]:
    yfinance_module = ingest_providers.load_yfinance_module()

    return ingest_providers.fetch_yfinance_records(
        yfinance_module.fetch_bars,
        symbol,
        tf,
        start=start,
        end=end,
        empty_reason="yfinance fallback returned no rows",
    )


def _should_shutdown(shutdown_file: Optional[Path]) -> bool:
    if shutdown_file is None:
        return False
    return shutdown_file.exists()


def _sleep_interval(seconds: float, *, stop_flag: StopSignal, shutdown_file: Optional[Path]) -> None:
    if seconds <= 0:
        return
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if stop_flag.requested or _should_shutdown(shutdown_file):
            return
        remaining = deadline - time.monotonic()
        time.sleep(min(1.0, max(0.05, remaining)))


def _ingest_symbol(symbol: str, config: WorkerConfig, *, now: datetime) -> Optional[dict]:
    snapshot_path = config.snapshot_path
    tf = config.tf
    raw_path = config.raw_root / symbol / f"{tf}.csv"
    validated_path = config.validated_root / symbol / f"{tf}.csv"
    features_path = config.features_root / symbol / f"{tf}.csv"

    last_ts = get_last_processed_ts(
        symbol,
        tf,
        snapshot_path=snapshot_path,
        validated_path=validated_path,
    )

    if last_ts is None:
        start = now - timedelta(minutes=config.lookback_minutes)
    else:
        start = last_ts - timedelta(minutes=config.lookback_minutes)

    try:
        dukascopy_records = _load_dukascopy_records(
            symbol,
            tf,
            start=start,
            end=now,
            offer_side=config.offer_side,
            freshness_threshold=config.freshness_threshold,
        )
        records: Iterable[dict] = dukascopy_records
        source_name = "dukascopy"
        fallback_reason: Optional[str] = None
    except ingest_providers.ProviderError as exc:
        fallback_reason = exc.reason
        dukascopy_records = []
    except Exception as exc:
        fallback_reason = f"fetch error: {exc}"
        dukascopy_records = []
    else:
        fallback_reason = None

    if fallback_reason is not None:
        print(
            "[live-ingest] Dukascopy unavailable, switching to yfinance fallback:",
            fallback_reason,
        )
        try:
            fallback_start = ingest_providers.compute_yfinance_fallback_start(
                last_ts=last_ts,
                lookback_minutes=config.lookback_minutes,
                now=now,
            )
            print(
                "[live-ingest] fetching yfinance bars",
                symbol,
                tf,
                fallback_start.isoformat(timespec="seconds"),
                now.isoformat(timespec="seconds"),
            )
            records = _load_yfinance_records(symbol, tf, start=fallback_start, end=now)
            source_name = "yfinance"
        except ingest_providers.ProviderError as exc:
            print(f"[live-ingest] yfinance fallback failed: {exc}")
            return None
        except Exception as exc:
            print(f"[live-ingest] yfinance fallback failed: {exc}")
            return None
    else:
        records = dukascopy_records
        source_name = "dukascopy"

    try:
        result = ingest_records(
            records,
            symbol=symbol,
            tf=tf,
            snapshot_path=snapshot_path,
            raw_path=raw_path,
            validated_path=validated_path,
            features_path=features_path,
            or_n=config.or_n,
            source_name=source_name,
        )
    except Exception as exc:
        print(f"[live-ingest] ingestion failed for {symbol}: {exc}")
        return None

    if isinstance(result, dict) and config.offer_side and source_name == "dukascopy":
        ingest_providers.mark_dukascopy_offer_side(
            result,
            offer_side=config.offer_side,
        )

    print(
        f"[live-ingest] {symbol} {source_name} rows={result['rows_validated']} "
        f"anomalies={result['anomalies_logged']} last_ts={result['last_ts_now']}"
    )
    return result


def _run_update_state(symbol: str, mode: str, *, bars_path: Path) -> None:
    from scripts import update_state as update_state_module

    args = [
        "--bars",
        str(bars_path),
        "--symbol",
        symbol,
        "--mode",
        mode,
    ]
    rc = update_state_module.main(args)
    if rc != 0:
        print(
            f"[live-ingest] update_state failed for {symbol}:{mode} with exit code {rc}"
        )


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Run a live ingestion worker that polls Dukascopy every interval",
    )
    parser.add_argument("--symbols", default=None, help="Comma-separated list of symbols")
    parser.add_argument("--symbol", dest="symbol", default=None, help="Single symbol override")
    parser.add_argument("--modes", default=None, help="Comma-separated strategy modes")
    parser.add_argument(
        "--mode",
        dest="mode",
        default=None,
        help="Single mode override (default: conservative)",
    )
    parser.add_argument("--tf", default="5m", help="Timeframe key (default 5m)")
    parser.add_argument(
        "--interval",
        type=float,
        default=300.0,
        help="Polling interval in seconds (default 300)",
    )
    parser.add_argument(
        "--lookback-minutes",
        type=int,
        default=180,
        help="Minutes to re-request when fetching new bars",
    )
    parser.add_argument(
        "--offer-side",
        default="bid",
        choices=["bid", "ask"],
        help="Offer side (bid/ask) to request from Dukascopy",
    )
    parser.add_argument(
        "--freshness-threshold-minutes",
        type=int,
        default=90,
        help="Maximum age of the last bar before triggering fallback",
    )
    parser.add_argument(
        "--snapshot",
        default=str(SNAPSHOT_PATH),
        help="Runtime snapshot JSON path",
    )
    parser.add_argument(
        "--raw-root",
        default=str(RAW_ROOT),
        help="Root directory for raw CSV storage",
    )
    parser.add_argument(
        "--validated-root",
        default=str(VALIDATED_ROOT),
        help="Root directory for validated CSV storage",
    )
    parser.add_argument(
        "--features-root",
        default=str(FEATURES_ROOT),
        help="Root directory for feature CSV storage",
    )
    parser.add_argument(
        "--shutdown-file",
        default=str(ROOT / "ops/live_ingest_worker.stop"),
        help="Path to a file whose presence triggers graceful shutdown",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=None,
        help="Optional cap on loop iterations (useful for tests)",
    )
    parser.add_argument(
        "--or-n",
        type=int,
        default=6,
        help="Opening range length passed to feature generation",
    )
    return parser.parse_args(argv)


def _build_config(args) -> WorkerConfig:
    symbols = _parse_csv_list(
        args.symbols or args.symbol,
        default=["USDJPY"],
    )
    modes = _parse_csv_list(
        args.modes or args.mode,
        default=["conservative"],
        case="lower",
    )

    shutdown_file = Path(args.shutdown_file).resolve() if args.shutdown_file else None

    return WorkerConfig(
        symbols=symbols,
        modes=modes,
        tf=args.tf,
        interval=max(0.0, float(args.interval)),
        lookback_minutes=max(1, int(args.lookback_minutes)),
        freshness_threshold=(
            int(args.freshness_threshold_minutes)
            if args.freshness_threshold_minutes is not None
            else None
        ),
        offer_side=(args.offer_side or "bid").lower(),
        snapshot_path=Path(args.snapshot).resolve(),
        raw_root=Path(args.raw_root).resolve(),
        validated_root=Path(args.validated_root).resolve(),
        features_root=Path(args.features_root).resolve(),
        shutdown_file=shutdown_file,
        max_iterations=(
            int(args.max_iterations) if args.max_iterations is not None else None
        ),
        or_n=max(1, int(args.or_n)),
    )


def main(argv=None) -> int:
    args = parse_args(argv)
    config = _build_config(args)

    stop_flag = StopSignal()

    def _handle_signal(signum, frame):  # pragma: no cover - signal handler
        print(f"[live-ingest] received signal {signum}, requesting shutdown")
        stop_flag.request()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _handle_signal)
        except (ValueError, AttributeError):  # pragma: no cover - platform specific
            pass

    iteration = 0
    print(
        "[live-ingest] starting worker",
        f"symbols={','.join(config.symbols)}",
        f"modes={','.join(config.modes)}",
        f"interval={config.interval}s",
        f"offer_side={config.offer_side}",
    )

    while not stop_flag.requested:
        if config.max_iterations is not None and iteration >= config.max_iterations:
            break
        if _should_shutdown(config.shutdown_file):
            print("[live-ingest] shutdown file detected before iteration")
            break

        iteration += 1
        now = utcnow_naive(dt_cls=datetime)
        print(f"[live-ingest] iteration {iteration} @ {now.isoformat(timespec='seconds')}")

        for symbol in config.symbols:
            if stop_flag.requested:
                break
            result = _ingest_symbol(symbol, config, now=now)
            if result is None:
                continue
            if result.get("rows_validated", 0) <= 0:
                continue
            bars_path = config.validated_root / symbol / f"{config.tf}.csv"
            for mode in config.modes:
                if stop_flag.requested:
                    break
                try:
                    _run_update_state(symbol, mode, bars_path=bars_path)
                except Exception as exc:
                    print(
                        f"[live-ingest] update_state raised for {symbol}:{mode}: {exc}"
                    )

        if stop_flag.requested:
            break
        if config.max_iterations is not None and iteration >= config.max_iterations:
            break
        if _should_shutdown(config.shutdown_file):
            print("[live-ingest] shutdown file detected; exiting")
            break

        _sleep_interval(
            config.interval,
            stop_flag=stop_flag,
            shutdown_file=config.shutdown_file,
        )

    print("[live-ingest] worker stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
