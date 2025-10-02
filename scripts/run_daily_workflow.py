#!/usr/bin/env python3
"""Daily workflow orchestration script."""
from __future__ import annotations
import argparse
import csv
import math
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.utils import yaml_compat as yaml


def _load_dukascopy_fetch() -> Callable[..., object]:
    """Return the Dukascopy fetch function, raising if unavailable."""

    from scripts.dukascopy_fetch import fetch_bars

    return fetch_bars


def _parse_naive_utc(timestamp: str) -> Optional[datetime]:
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


def _format_utc_iso(dt_value: datetime) -> str:
    """Return an ISO8601 string in UTC for *dt_value*."""

    if dt_value.tzinfo is None:
        dt_value = dt_value.replace(tzinfo=timezone.utc)
    else:
        dt_value = dt_value.astimezone(timezone.utc)

    return dt_value.replace(microsecond=0).isoformat()


def _load_last_validated_entry(validated_path: Path) -> Optional[Dict[str, object]]:
    """Return the most recent validated row with parsed numeric fields."""

    if not validated_path.exists():
        return None

    last_row: Optional[Dict[str, object]] = None
    with validated_path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            last_row = row

    if not last_row:
        return None

    timestamp = _parse_naive_utc(str(last_row.get("timestamp", "")))
    if timestamp is None:
        return None

    try:
        return {
            "timestamp": timestamp,
            "symbol": str(last_row.get("symbol", "")),
            "tf": str(last_row.get("tf", "")),
            "o": float(last_row.get("o", 0.0)),
            "h": float(last_row.get("h", 0.0)),
            "l": float(last_row.get("l", 0.0)),
            "c": float(last_row.get("c", 0.0)),
            "v": float(last_row.get("v", 0.0) or 0.0),
            "spread": float(last_row.get("spread", 0.0) or 0.0),
        }
    except Exception:
        return None


def _truncate_to_tf(dt_value: datetime, *, tf_minutes: int) -> datetime:
    """Align a datetime to the timeframe boundary (floor)."""

    remainder = dt_value.minute % tf_minutes
    if remainder:
        dt_value -= timedelta(minutes=remainder)
    return dt_value.replace(second=0, microsecond=0)


def _compute_synthetic_target(now: datetime, *, tf_minutes: int) -> datetime:
    """Return the latest synthetic bar timestamp aligned to timeframe boundaries."""

    guard = now - timedelta(minutes=tf_minutes)
    aligned = _truncate_to_tf(guard, tf_minutes=tf_minutes)
    if aligned > guard:
        aligned -= timedelta(minutes=tf_minutes)
    return aligned


def _generate_synthetic_bars(
    *,
    base_entry: Dict[str, object],
    target_end: datetime,
    tf_minutes: int,
    symbol: str,
    tf: str,
) -> List[Dict[str, object]]:
    """Generate deterministic synthetic OHLCV rows up to the desired end timestamp."""

    start_dt = base_entry["timestamp"] + timedelta(minutes=tf_minutes)
    if start_dt > target_end:
        return []

    records: List[Dict[str, object]] = []
    last_close = float(base_entry["c"])
    spread = float(base_entry.get("spread", 0.0))

    current_dt = start_dt
    step = 1
    while current_dt <= target_end:
        wave = math.sin(step / 6.0) * 0.06
        drift = math.cos(step / 14.0) * 0.04
        open_px = last_close + wave
        close_px = open_px + drift
        high_px = max(open_px, close_px) + 0.01
        low_px = min(open_px, close_px) - 0.01
        volume = 120.0 + (step % 9) * 15.0

        records.append(
            {
                "timestamp": current_dt.strftime("%Y-%m-%dT%H:%M:%S"),
                "symbol": symbol,
                "tf": tf,
                "o": round(open_px, 6),
                "h": round(high_px, 6),
                "l": round(low_px, 6),
                "c": round(close_px, 6),
                "v": round(volume, 6),
                "spread": spread,
            }
        )

        last_close = close_px
        current_dt += timedelta(minutes=tf_minutes)
        step += 1

    return records


def _merge_ingest_results(
    primary: Optional[Dict[str, object]],
    extra: Optional[Dict[str, object]],
) -> Optional[Dict[str, object]]:
    """Combine ingestion metadata from multiple passes."""

    if primary is None:
        return extra
    if extra is None:
        return primary

    merged = primary.copy()
    merged_sources = [
        str(primary.get("source") or ""),
        str(extra.get("source") or ""),
    ]
    merged["source"] = "+".join([s for s in merged_sources if s])

    for key in (
        "rows_raw",
        "rows_validated",
        "rows_featured",
        "anomalies_logged",
        "gaps_detected",
    ):
        merged[key] = (primary.get(key) or 0) + (extra.get(key) or 0)

    if extra.get("last_ts_now"):
        merged["last_ts_now"] = extra["last_ts_now"]

    if primary.get("local_backup_path") and not extra.get("local_backup_path"):
        merged.setdefault("local_backup_path", primary["local_backup_path"])
    elif extra.get("local_backup_path"):
        merged["local_backup_path"] = extra["local_backup_path"]

    return merged


def _ingest_local_csv_backup(
    *,
    ingest_records_func,
    symbol: str,
    tf: str,
    snapshot_path: Path,
    raw_path: Path,
    validated_path: Path,
    features_path: Path,
    backup_path: Optional[Path] = None,
    enable_synthetic: bool = True,
) -> Dict[str, object]:
    """Ingest bars from the bundled CSV backup for sandbox execution."""

    from scripts import pull_prices as pull_module

    candidate_path = backup_path
    if candidate_path is None:
        candidate_path = ROOT / pull_module.DEFAULT_SOURCE

    if not candidate_path.exists():
        raise RuntimeError(f"local CSV backup not found: {candidate_path}")

    with candidate_path.open(newline="", encoding="utf-8") as fh:
        reader: Iterable[Dict[str, object]] = csv.DictReader(fh)
        result = ingest_records_func(
            reader,
            symbol=symbol,
            tf=tf,
            snapshot_path=snapshot_path,
            raw_path=raw_path,
            validated_path=validated_path,
            features_path=features_path,
            source_name=f"local_csv:{candidate_path.name}",
        )

    if isinstance(result, dict):
        result.setdefault("local_backup_path", str(candidate_path))

    if not enable_synthetic:
        return result

    tf_minutes = 5
    if tf.endswith("m"):
        try:
            tf_minutes = max(1, int(tf[:-1] or 5))
        except ValueError:
            tf_minutes = 5
    elif tf.endswith("h"):
        try:
            tf_minutes = max(1, int(tf[:-1] or 1) * 60)
        except ValueError:
            tf_minutes = 60
    now = datetime.utcnow()
    target_end = _compute_synthetic_target(now, tf_minutes=tf_minutes)

    latest_ts = _parse_naive_utc(str(result.get("last_ts_now", "")))
    if latest_ts is None:
        last_entry = _load_last_validated_entry(validated_path)
        if last_entry is None:
            return result
    else:
        last_entry = _load_last_validated_entry(validated_path)

    if last_entry is None:
        return result

    latest_ts = last_entry["timestamp"]
    if latest_ts >= target_end:
        return result

    synthetic_rows = _generate_synthetic_bars(
        base_entry=last_entry,
        target_end=target_end,
        tf_minutes=tf_minutes,
        symbol=symbol,
        tf=tf,
    )

    if not synthetic_rows:
        return result

    synthetic_result = ingest_records_func(
        synthetic_rows,
        symbol=symbol,
        tf=tf,
        snapshot_path=snapshot_path,
        raw_path=raw_path,
        validated_path=validated_path,
        features_path=features_path,
        source_name="synthetic_local",
    )

    merged = _merge_ingest_results(result, synthetic_result)
    return merged if merged is not None else result


def _split_source_chain(source_text: Optional[str]) -> List[Dict[str, str]]:
    """Break a merged source string into structured entries."""

    if not source_text:
        return []

    entries: List[Dict[str, str]] = []
    for raw in source_text.split("+"):
        piece = raw.strip()
        if not piece:
            continue
        if ":" in piece:
            label, detail = piece.split(":", 1)
            item = {"source": label.strip() or piece}
            detail = detail.strip()
            if detail:
                item["detail"] = detail
        else:
            item = {"source": piece}
        entries.append(item)
    return entries


def _compute_freshness_minutes(last_ts_raw: Optional[str], now: datetime) -> Optional[float]:
    """Return the freshness delta in minutes between now and the last timestamp."""

    parsed = _parse_naive_utc(last_ts_raw or "")
    if parsed is None:
        return None

    delta = now - parsed
    minutes = max(delta.total_seconds() / 60.0, 0.0)
    return round(minutes, 3)


def _prepare_ingest_metadata(
    *,
    symbol: str,
    tf: str,
    snapshot_path: Path,
    result: Dict[str, Any],
    fallback_notes: List[Dict[str, str]],
    primary_source: str,
    now: datetime,
) -> Optional[Dict[str, Any]]:
    """Assemble structured ingestion metadata for persistence."""

    if not isinstance(result, dict):
        return None

    raw_source = str(result.get("source") or "")
    source_chain = _split_source_chain(raw_source)
    last_ts_raw = result.get("last_ts_now")
    freshness = _compute_freshness_minutes(last_ts_raw, now)

    metadata: Dict[str, Any] = {
        "primary_source": primary_source,
        "source_label": raw_source or None,
        "source_chain": source_chain,
        "rows_raw": int(result.get("rows_raw", 0) or 0),
        "rows_validated": int(result.get("rows_validated", 0) or 0),
        "rows_featured": int(result.get("rows_featured", 0) or 0),
        "anomalies_logged": int(result.get("anomalies_logged", 0) or 0),
        "gaps_detected": int(result.get("gaps_detected", 0) or 0),
        "last_ts_now": last_ts_raw,
        "freshness_minutes": freshness,
        "snapshot_path": str(snapshot_path),
    }

    metadata["last_ingest_at"] = _format_utc_iso(now)

    offer_side = result.get("dukascopy_offer_side")
    if offer_side:
        metadata["dukascopy_offer_side"] = str(offer_side)

    if fallback_notes:
        metadata["fallbacks"] = fallback_notes

    metadata["synthetic_extension"] = any(
        entry.get("source") == "synthetic_local" for entry in source_chain
    )

    backup_path = result.get("local_backup_path") if isinstance(result, dict) else None
    if isinstance(backup_path, str) and backup_path:
        metadata["local_backup_path"] = backup_path

    return metadata


def _persist_ingest_metadata(
    *,
    symbol: str,
    tf: str,
    snapshot_path: Path,
    result: Dict[str, Any],
    fallback_notes: List[Dict[str, str]],
    primary_source: str,
    now: datetime,
) -> None:
    metadata = _prepare_ingest_metadata(
        symbol=symbol,
        tf=tf,
        snapshot_path=snapshot_path,
        result=result,
        fallback_notes=fallback_notes,
        primary_source=primary_source,
        now=now,
    )
    if not metadata:
        return

    try:
        from scripts.pull_prices import record_ingest_metadata
    except Exception as exc:  # pragma: no cover - unexpected import failure
        print(f"[wf] unable to import record_ingest_metadata: {exc}")
        return

    try:
        record_ingest_metadata(
            symbol,
            tf,
            metadata,
            snapshot_path=snapshot_path,
        )
    except Exception as exc:  # pragma: no cover - persistence failures
        print(f"[wf] failed to persist ingest metadata: {exc}")


def _append_fallback(
    fallbacks: List[Dict[str, str]],
    *,
    stage: str,
    reason: str,
    next_source: Optional[str] = None,
    detail: Optional[str] = None,
) -> None:
    note = {"stage": stage, "reason": reason}
    if next_source:
        note["next_source"] = next_source
    if detail:
        note["detail"] = detail
    fallbacks.append(note)


def run_cmd(cmd):
    print(f"[wf] running: {' '.join(cmd)}")
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        print(f"[wf] command failed with exit code {result.returncode}")
    return result.returncode


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Daily workflow orchestrator")
    parser.add_argument("--symbol", default="USDJPY")
    parser.add_argument("--mode", default="conservative", choices=["conservative", "bridge"])
    parser.add_argument("--equity", default="100000")
    parser.add_argument("--ingest", action="store_true", help="Run pull_prices to append latest bars")
    parser.add_argument(
        "--use-dukascopy",
        action="store_true",
        help="Fetch latest bars via Dukascopy before ingestion",
    )
    parser.add_argument(
        "--use-api",
        action="store_true",
        help="Fetch latest bars via REST API before ingestion",
    )
    parser.add_argument(
        "--use-yfinance",
        action="store_true",
        help="Fetch latest bars via yfinance before ingestion",
    )
    parser.add_argument(
        "--dukascopy-lookback-minutes",
        type=int,
        default=180,
        help="Minutes of history to re-request when using Dukascopy ingestion",
    )
    parser.add_argument(
        "--dukascopy-offer-side",
        default="bid",
        choices=["bid", "ask"],
        help="Offer side (bid/ask) requested from Dukascopy",
    )
    parser.add_argument(
        "--yfinance-lookback-minutes",
        type=int,
        default=60,
        help="Minutes of history to re-request when using yfinance ingestion",
    )
    parser.add_argument(
        "--local-backup-csv",
        default=None,
        help=(
            "Path to the CSV used when falling back to local ingestion; "
            "defaults to pull_prices.DEFAULT_SOURCE"
        ),
    )
    parser.add_argument(
        "--dukascopy-freshness-threshold-minutes",
        type=int,
        default=90,
        help="Minutes before a Dukascopy fetch is considered stale and triggers fallback",
    )
    parser.add_argument(
        "--api-provider",
        default=None,
        help="Override API provider defined in configs/api_ingest.yml",
    )
    parser.add_argument(
        "--api-config",
        default=str(ROOT / "configs/api_ingest.yml"),
        help="Path to API ingest configuration file",
    )
    parser.add_argument(
        "--api-credentials",
        default=str(ROOT / "configs/api_keys.yml"),
        help="Path to API credential store",
    )
    parser.add_argument(
        "--api-lookback-minutes",
        type=int,
        default=None,
        help="Override history window when using API ingestion",
    )
    parser.add_argument("--update-state", action="store_true", help="Replay new bars and update state.json")
    parser.add_argument("--benchmarks", action="store_true", help="Run baseline + rolling benchmarks")
    parser.add_argument("--state-health", action="store_true", help="Run state health checker")
    parser.add_argument("--benchmark-summary", action="store_true", help="Aggregate benchmark reports")
    parser.add_argument(
        "--check-benchmark-freshness",
        action="store_true",
        help="Validate benchmark timestamps recorded in runtime snapshot",
    )
    parser.add_argument("--benchmark-windows", default="365,180,90", help="Rolling windows in days for benchmarks")
    parser.add_argument(
        "--min-sharpe",
        type=float,
        default=None,
        help="Warn when Sharpe ratio falls below this value",
    )
    parser.add_argument(
        "--min-win-rate",
        type=float,
        default=None,
        help="Warn when win_rate falls below this value",
    )
    parser.add_argument(
        "--max-drawdown",
        type=float,
        default=None,
        help="Warn when |max_drawdown| exceeds this value (pips)",
    )
    parser.add_argument(
        "--alert-pips",
        type=float,
        default=50.0,
        help="Abs diff in total_pips to trigger alert",
    )
    parser.add_argument(
        "--alert-winrate",
        type=float,
        default=0.05,
        help="Abs diff in win_rate to trigger alert",
    )
    parser.add_argument(
        "--alert-sharpe",
        type=float,
        default=0.15,
        help="Abs diff in Sharpe ratio to trigger alert",
    )
    parser.add_argument(
        "--alert-max-drawdown",
        type=float,
        default=40.0,
        help="Abs diff in max_drawdown (pips) to trigger alert",
    )
    parser.add_argument("--optimize", action="store_true", help="Run parameter optimization")
    parser.add_argument("--analyze-latency", action="store_true", help="Analyze signal latency")
    parser.add_argument("--archive-state", action="store_true", help="Archive state.json files")
    parser.add_argument("--bars", default=None, help="Override bars CSV path (default: validated/<symbol>/5m.csv)")
    parser.add_argument("--webhook", default=None)
    parser.add_argument(
        "--benchmark-freshness-max-age-hours",
        type=float,
        default=None,
        help="Override max age threshold (hours) for benchmark freshness checks",
    )
    parser.add_argument(
        "--benchmark-freshness-targets",
        default=None,
        help="Comma-separated symbol:mode targets for freshness checks",
    )
    args = parser.parse_args(argv)

    local_backup_path: Optional[Path] = None
    if args.local_backup_csv:
        candidate = Path(args.local_backup_csv)
        if not candidate.is_absolute():
            candidate = (ROOT / candidate).resolve()
        else:
            candidate = candidate.resolve()
        local_backup_path = candidate

    symbol_input = args.symbol.upper()
    if symbol_input.endswith("=X"):
        symbol_upper = symbol_input[:-2]
    else:
        symbol_upper = symbol_input
    args.symbol = symbol_upper

    bars_csv = args.bars or str(ROOT / f"validated/{symbol_upper}/5m.csv")

    if args.ingest:
        selected_sources = [
            flag
            for flag in (args.use_dukascopy, args.use_api, args.use_yfinance)
            if flag
        ]
        if len(selected_sources) > 1:
            print("[wf] specify at most one of --use-dukascopy/--use-api/--use-yfinance")
            return 1

        if args.use_dukascopy:
            try:
                from scripts.pull_prices import ingest_records, get_last_processed_ts
            except RuntimeError as exc:
                print(f"[wf] Dukascopy ingestion unavailable: {exc}")
                return 1
            except Exception as exc:  # pragma: no cover - unexpected import failure
                print(f"[wf] Dukascopy ingestion failed to initialize: {exc}")
                return 1

            fetch_bars = None
            fallback_reason = None
            fallback_notes: List[Dict[str, str]] = []
            try:
                fetch_bars = _load_dukascopy_fetch()
            except Exception as exc:  # pragma: no cover - optional dependency
                fallback_reason = f"initialization error: {exc}"

            snapshot_path = ROOT / "ops/runtime_snapshot.json"
            tf = "5m"
            symbol_upper = args.symbol.upper()
            validated_path = ROOT / "validated" / symbol_upper / f"{tf}.csv"
            raw_path = ROOT / "raw" / symbol_upper / f"{tf}.csv"
            features_path = ROOT / "features" / symbol_upper / f"{tf}.csv"

            last_ts = get_last_processed_ts(
                symbol_upper,
                tf,
                snapshot_path=snapshot_path,
                validated_path=validated_path,
            )
            now = datetime.utcnow()
            lookback = max(5, args.dukascopy_lookback_minutes)
            if last_ts is not None:
                start = last_ts - timedelta(minutes=lookback)
            else:
                start = now - timedelta(minutes=lookback)

            offer_side = (args.dukascopy_offer_side or "bid").lower()
            print(
                "[wf] fetching Dukascopy bars",
                args.symbol,
                tf,
                start.isoformat(timespec="seconds"),
                now.isoformat(timespec="seconds"),
                f"offer_side={offer_side}",
            )

            dukascopy_records = []
            if fallback_reason is None and fetch_bars is not None:
                try:
                    dukascopy_records = list(
                        fetch_bars(
                            args.symbol,
                            tf,
                            start=start,
                            end=now,
                            offer_side=offer_side,
                        )
                    )
                except Exception as exc:
                    fallback_reason = f"fetch error: {exc}"

            freshness_threshold = args.dukascopy_freshness_threshold_minutes
            if fallback_reason is None:
                if not dukascopy_records:
                    fallback_reason = "no rows returned"
                else:
                    last_record_ts = str(dukascopy_records[-1].get("timestamp", ""))
                    try:
                        parsed_last = datetime.fromisoformat(
                            last_record_ts.replace("Z", "+00:00")
                        )
                        if parsed_last.tzinfo is not None:
                            parsed_last = (
                                parsed_last.astimezone(timezone.utc)
                                .replace(tzinfo=None)
                            )
                    except Exception:
                        parsed_last = None

                    if parsed_last is None:
                        fallback_reason = "could not parse last timestamp"
                    else:
                        if freshness_threshold and freshness_threshold > 0:
                            max_age = timedelta(minutes=freshness_threshold)
                            if now - parsed_last > max_age:
                                fallback_reason = (
                                    "stale data: "
                                    f"last_ts={parsed_last.isoformat(timespec='seconds')}"
                                )

            records_to_ingest = dukascopy_records
            source_name = "dukascopy"
            result: Optional[Dict[str, object]] = None

            def _run_local_csv_fallback(reason: str) -> Optional[Dict[str, object]]:
                print("[wf] local CSV fallback triggered:", reason)
                try:
                    result = _ingest_local_csv_backup(
                        ingest_records_func=ingest_records,
                        symbol=symbol_upper,
                        tf=tf,
                        snapshot_path=snapshot_path,
                        raw_path=raw_path,
                        validated_path=validated_path,
                        features_path=features_path,
                        backup_path=local_backup_path,
                    )
                except Exception as backup_exc:  # pragma: no cover - unexpected failure
                    print(f"[wf] local CSV fallback unavailable: {backup_exc}")
                    return None
                else:
                    detail_path = None
                    next_source = None
                    if isinstance(result, dict):
                        backup_path_value = result.get("local_backup_path")
                        if isinstance(backup_path_value, str) and backup_path_value:
                            detail_path = backup_path_value
                        source_value = str(result.get("source") or "")
                        if "synthetic_local" in source_value:
                            next_source = "synthetic_local"
                    _append_fallback(
                        fallback_notes,
                        stage="local_csv",
                        reason="local CSV fallback executed",
                        next_source=next_source,
                        detail=detail_path,
                    )
                    return result

            if fallback_reason is not None:
                _append_fallback(
                    fallback_notes,
                    stage="dukascopy",
                    reason=fallback_reason,
                    next_source="yfinance",
                )
                print(
                    "[wf] Dukascopy unavailable, switching to yfinance fallback:",
                    fallback_reason,
                )
                try:
                    from scripts import yfinance_fetch as yfinance_module
                except Exception as exc:  # pragma: no cover - optional dependency
                    reason = f"yfinance import failed: {exc}"
                    _append_fallback(
                        fallback_notes,
                        stage="yfinance",
                        reason=reason,
                        next_source="local_csv",
                    )
                    result = _run_local_csv_fallback(reason)
                    if result is None:
                        return 1
                    source_name = "local_csv"
                    records_to_ingest = None
                else:
                    fallback_window_days = 7
                    fallback_window = timedelta(days=fallback_window_days)
                    yf_lookback_minutes = max(5, args.yfinance_lookback_minutes or 0)
                    if last_ts is not None:
                        fallback_start = last_ts - timedelta(minutes=yf_lookback_minutes)
                    else:
                        minutes = max(
                            yf_lookback_minutes, fallback_window_days * 24 * 60
                        )
                        fallback_start = now - timedelta(minutes=minutes)
                    fallback_start = max(fallback_start, now - fallback_window)
                    if fallback_start > now:
                        fallback_start = now
                    fetch_symbol = yfinance_module.resolve_ticker(symbol_upper)
                    print(
                        "[wf] fetching yfinance bars",
                        fetch_symbol,
                        f"(fallback for {symbol_upper})",
                        tf,
                        fallback_start.isoformat(timespec="seconds"),
                        now.isoformat(timespec="seconds"),
                    )

                    try:
                        yfinance_records = list(
                            yfinance_module.fetch_bars(
                                args.symbol,
                                tf,
                                start=fallback_start,
                                end=now,
                            )
                        )
                    except Exception as exc:
                        reason = f"yfinance fallback failed: {exc}"
                        _append_fallback(
                            fallback_notes,
                            stage="yfinance",
                            reason=reason,
                            next_source="local_csv",
                        )
                        result = _run_local_csv_fallback(reason)
                        if result is None:
                            return 1
                        source_name = "local_csv"
                        records_to_ingest = None
                    else:
                        if not yfinance_records:
                            reason = "yfinance fallback returned no rows"
                            _append_fallback(
                                fallback_notes,
                                stage="yfinance",
                                reason=reason,
                                next_source="local_csv",
                            )
                            result = _run_local_csv_fallback(reason)
                            if result is None:
                                return 1
                            source_name = "local_csv"
                            records_to_ingest = None
                        else:
                            records_to_ingest = yfinance_records
                            source_name = "yfinance"

            if result is None:
                try:
                    result = ingest_records(
                        records_to_ingest,
                        symbol=symbol_upper,
                        tf=tf,
                        snapshot_path=snapshot_path,
                        raw_path=raw_path,
                        validated_path=validated_path,
                        features_path=features_path,
                        source_name=source_name,
                    )
                except Exception as exc:
                    print(f"[wf] ingestion failed: {exc}")
                    return 1

            label = source_name
            detail = result.get("source") if isinstance(result, dict) else None
            suffix = f" ({detail})" if detail and detail != label else ""
            print(
                f"[wf] {label}_ingest{suffix}",
                f"rows={result['rows_validated']}",
                f"last_ts={result['last_ts_now']}",
            )

            finish_now = datetime.utcnow()
            if isinstance(result, dict) and offer_side:
                result.setdefault("dukascopy_offer_side", offer_side)
            _persist_ingest_metadata(
                symbol=symbol_upper,
                tf=tf,
                snapshot_path=snapshot_path,
                result=result,
                fallback_notes=fallback_notes,
                primary_source="dukascopy",
                now=finish_now,
            )
        elif args.use_yfinance:
            try:
                from scripts.pull_prices import ingest_records, get_last_processed_ts
            except RuntimeError as exc:
                print(f"[wf] yfinance ingestion unavailable: {exc}")
                return 1
            except Exception as exc:  # pragma: no cover - import error
                print(f"[wf] yfinance ingestion failed to initialize pull_prices: {exc}")
                return 1

            snapshot_path = ROOT / "ops/runtime_snapshot.json"
            tf = "5m"
            symbol_upper = args.symbol
            validated_path = ROOT / "validated" / symbol_upper / f"{tf}.csv"
            raw_path = ROOT / "raw" / symbol_upper / f"{tf}.csv"
            features_path = ROOT / "features" / symbol_upper / f"{tf}.csv"

            fallback_notes: List[Dict[str, str]] = []

            def _run_local_csv_fallback(reason: str) -> Optional[Dict[str, object]]:
                _append_fallback(
                    fallback_notes,
                    stage="yfinance",
                    reason=reason,
                    next_source="local_csv",
                )
                print("[wf] local CSV fallback triggered:", reason)
                try:
                    result = _ingest_local_csv_backup(
                        ingest_records_func=ingest_records,
                        symbol=symbol_upper,
                        tf=tf,
                        snapshot_path=snapshot_path,
                        raw_path=raw_path,
                        validated_path=validated_path,
                        features_path=features_path,
                        backup_path=local_backup_path,
                    )
                except Exception as backup_exc:  # pragma: no cover - unexpected failure
                    print(f"[wf] local CSV fallback unavailable: {backup_exc}")
                    return None
                else:
                    detail_path = None
                    next_source = None
                    if isinstance(result, dict):
                        backup_path_value = result.get("local_backup_path")
                        if isinstance(backup_path_value, str) and backup_path_value:
                            detail_path = backup_path_value
                        source_value = str(result.get("source") or "")
                        if "synthetic_local" in source_value:
                            next_source = "synthetic_local"
                    _append_fallback(
                        fallback_notes,
                        stage="local_csv",
                        reason="local CSV fallback executed",
                        next_source=next_source,
                        detail=detail_path,
                    )
                    return result

            try:
                from scripts.yfinance_fetch import fetch_bars, resolve_ticker
            except Exception as exc:
                result = _run_local_csv_fallback(f"yfinance module unavailable: {exc}")
                if result is None:
                    return 1
                label = "local_csv"
            else:
                last_ts = get_last_processed_ts(
                    symbol_upper,
                    tf,
                    snapshot_path=snapshot_path,
                    validated_path=validated_path,
                )
                lookback = max(5, args.yfinance_lookback_minutes)
                now = datetime.utcnow()
                if last_ts is not None:
                    start = last_ts - timedelta(minutes=lookback)
                else:
                    start = now - timedelta(minutes=lookback)

                fetch_symbol = resolve_ticker(symbol_upper)
                print(
                    "[wf] fetching yfinance bars",
                    fetch_symbol,
                    f"(source {symbol_upper})",
                    tf,
                    start.isoformat(timespec="seconds"),
                    now.isoformat(timespec="seconds"),
                )

                try:
                    records_list = list(
                        fetch_bars(
                            args.symbol,
                            tf,
                            start=start,
                            end=now,
                        )
                        )
                except Exception as exc:
                    reason = f"yfinance ingestion failed: {exc}"
                    result = _run_local_csv_fallback(reason)
                    if result is None:
                        return 1
                    label = "local_csv"
                else:
                    if not records_list:
                        reason = "yfinance ingestion returned no rows"
                        result = _run_local_csv_fallback(reason)
                        if result is None:
                            return 1
                        label = "local_csv"
                    else:
                        try:
                            result = ingest_records(
                                records_list,
                                symbol=symbol_upper,
                                tf=tf,
                                snapshot_path=snapshot_path,
                                raw_path=raw_path,
                                validated_path=validated_path,
                                features_path=features_path,
                                source_name="yfinance",
                            )
                        except Exception as exc:
                            reason = (
                                f"yfinance ingestion failed during ingest: {exc}"
                            )
                            result = _run_local_csv_fallback(reason)
                            if result is None:
                                return 1
                            label = "local_csv"
                        else:
                            label = "yfinance"

            detail = result.get("source") if isinstance(result, dict) else None
            suffix = f" ({detail})" if detail and detail != label else ""
            print(
                f"[wf] {label}_ingest{suffix}",
                f"rows={result['rows_validated']}",
                f"last_ts={result['last_ts_now']}",
            )

            finish_now = datetime.utcnow()
            _persist_ingest_metadata(
                symbol=symbol_upper,
                tf=tf,
                snapshot_path=snapshot_path,
                result=result,
                fallback_notes=fallback_notes,
                primary_source="yfinance",
                now=finish_now,
            )
        elif args.use_api:
            try:
                from scripts.fetch_prices_api import fetch_prices
                from scripts.pull_prices import ingest_records, get_last_processed_ts
            except Exception as exc:  # pragma: no cover - import failure
                print(f"[wf] API ingestion unavailable: {exc}")
                return 1

            snapshot_path = ROOT / "ops/runtime_snapshot.json"
            tf = "5m"
            symbol_upper = args.symbol.upper()
            validated_path = ROOT / "validated" / symbol_upper / f"{tf}.csv"
            raw_path = ROOT / "raw" / symbol_upper / f"{tf}.csv"
            features_path = ROOT / "features" / symbol_upper / f"{tf}.csv"
            fallback_notes: List[Dict[str, str]] = []

            last_ts = get_last_processed_ts(
                symbol_upper,
                tf,
                snapshot_path=snapshot_path,
                validated_path=validated_path,
            )
            now = datetime.utcnow()
            lookback_default = args.api_lookback_minutes
            if lookback_default is None:
                try:
                    with Path(args.api_config).open(encoding="utf-8") as fh:
                        cfg = yaml.safe_load(fh) or {}
                    provider_name = args.api_provider or cfg.get("default_provider")
                    providers = cfg.get("providers", {})
                    provider_cfg = providers.get(provider_name) if provider_name else None
                    lookback_default = (
                        args.api_lookback_minutes
                        or (provider_cfg or {}).get("lookback_minutes")
                        or cfg.get("lookback_minutes")
                    )
                except Exception:
                    lookback_default = None
            lookback_minutes = max(5, int(lookback_default or 120))

            if last_ts is not None:
                start = last_ts - timedelta(minutes=lookback_minutes)
            else:
                start = now - timedelta(minutes=lookback_minutes)

            print(
                "[wf] fetching API bars",
                args.symbol,
                tf,
                start.isoformat(timespec="seconds"),
                now.isoformat(timespec="seconds"),
            )

            try:
                records = fetch_prices(
                    symbol_upper,
                    tf,
                    start=start,
                    end=now,
                    provider=args.api_provider,
                    config_path=args.api_config,
                    credentials_path=args.api_credentials,
                )
                result = ingest_records(
                    records,
                    symbol=symbol_upper,
                    tf=tf,
                    snapshot_path=snapshot_path,
                    raw_path=raw_path,
                    validated_path=validated_path,
                    features_path=features_path,
                    source_name="api",
                )
            except Exception as exc:
                print(f"[wf] API ingestion failed: {exc}")
                return 1

            print(
                "[wf] api_ingest",
                f"rows={result['rows_validated']}",
                f"last_ts={result['last_ts_now']}",
            )

            finish_now = datetime.utcnow()
            _persist_ingest_metadata(
                symbol=symbol_upper,
                tf=tf,
                snapshot_path=snapshot_path,
                result=result,
                fallback_notes=fallback_notes,
                primary_source="api",
                now=finish_now,
            )
        else:
            cmd = [
                sys.executable,
                str(ROOT / "scripts/pull_prices.py"),
                "--source",
                str(ROOT / "data/usdjpy_5m_2018-2024_utc.csv"),
                "--symbol",
                args.symbol,
            ]
            exit_code = run_cmd(cmd)
            if exit_code:
                return exit_code

    if args.update_state:
        cmd = [sys.executable, str(ROOT / "scripts/update_state.py"),
               "--bars", bars_csv,
               "--symbol", args.symbol,
               "--mode", args.mode,
               "--equity", args.equity,
               "--state-out", str(ROOT / "runs/active/state.json")]
        exit_code = run_cmd(cmd)
        if exit_code:
            return exit_code

    if args.benchmarks:
        # Use the pipeline script which orchestrates runs and summary
        cmd = [
            sys.executable,
            str(ROOT / "scripts/run_benchmark_pipeline.py"),
            "--bars",
            bars_csv,
            "--symbol",
            args.symbol,
            "--mode",
            args.mode,
            "--equity",
            str(args.equity),
            "--windows",
            args.benchmark_windows,
        ]
        if args.alert_pips is not None:
            cmd += ["--alert-pips", str(args.alert_pips)]
        if args.alert_winrate is not None:
            cmd += ["--alert-winrate", str(args.alert_winrate)]
        if args.alert_sharpe is not None:
            cmd += ["--alert-sharpe", str(args.alert_sharpe)]
        if args.alert_max_drawdown is not None:
            cmd += ["--alert-max-drawdown", str(args.alert_max_drawdown)]
        if args.min_sharpe is not None:
            cmd += ["--min-sharpe", str(args.min_sharpe)]
        if args.min_win_rate is not None:
            cmd += ["--min-win-rate", str(args.min_win_rate)]
        if args.max_drawdown is not None:
            cmd += ["--max-drawdown", str(args.max_drawdown)]
        if args.webhook:
            cmd += ["--webhook", args.webhook]
        exit_code = run_cmd(cmd)
        if exit_code:
            return exit_code

    if args.state_health:
        cmd = [sys.executable, str(ROOT / "scripts/check_state_health.py"),
               "--state", str(ROOT / "runs/active/state.json"),
               "--json-out", str(ROOT / "ops/health/state_checks.json")]
        exit_code = run_cmd(cmd)
        if exit_code:
            return exit_code

    if args.benchmark_summary:
        cmd = [
            sys.executable,
            str(ROOT / "scripts/report_benchmark_summary.py"),
            "--symbol",
            args.symbol,
            "--mode",
            args.mode,
            "--reports-dir",
            str(ROOT / "reports"),
            "--json-out",
            str(ROOT / "reports/benchmark_summary.json"),
            "--plot-out",
            str(ROOT / "reports/benchmark_summary.png"),
            "--windows",
            args.benchmark_windows,
        ]
        if args.min_sharpe is not None:
            cmd += ["--min-sharpe", str(args.min_sharpe)]
        if args.min_win_rate is not None:
            cmd += ["--min-win-rate", str(args.min_win_rate)]
        if args.max_drawdown is not None:
            cmd += ["--max-drawdown", str(args.max_drawdown)]
        if args.webhook:
            cmd += ["--webhook", args.webhook]
        exit_code = run_cmd(cmd)
        if exit_code:
            return exit_code

    if args.check_benchmark_freshness:
        cmd = [
            sys.executable,
            str(ROOT / "scripts/check_benchmark_freshness.py"),
            "--snapshot",
            str(ROOT / "ops/runtime_snapshot.json"),
            "--max-age-hours",
            str(
                args.benchmark_freshness_max_age_hours
                if args.benchmark_freshness_max_age_hours is not None
                else 6.0
            ),
        ]
        if args.benchmark_freshness_targets:
            for raw_target in args.benchmark_freshness_targets.split(","):
                target = raw_target.strip()
                if target:
                    cmd += ["--target", target]
        else:
            cmd += ["--target", f"{args.symbol}:{args.mode}"]
        exit_code = run_cmd(cmd)
        if exit_code:
            return exit_code

    if args.optimize:
        cmd = [
            sys.executable,
            str(ROOT / "scripts/auto_optimize.py"),
            "--opt-args",
            "--top-k",
            "5",
            "--min-trades",
            "300",
            "--rebuild-index",
            "--csv",
            str(ROOT / "data/usdjpy_5m_2018-2024_utc.csv"),
            "--symbol",
            "USDJPY",
            "--mode",
            "conservative",
            "--or-n",
            "4,6",
            "--k-tp",
            "0.8,1.0",
            "--k-sl",
            "0.4,0.6",
            "--threshold-lcb",
            "0.3",
            "--allowed-sessions",
            "LDN,NY",
            "--warmup",
            "10",
            "--include-expected-slip",
            "--report",
            str(ROOT / "reports/auto_optimize.json"),
        ]
        if args.webhook:
            cmd += ["--webhook", args.webhook]
        exit_code = run_cmd(cmd)
        if exit_code:
            return exit_code

    if args.analyze_latency:
        cmd = [
            sys.executable,
            str(ROOT / "scripts/analyze_signal_latency.py"),
            "--input",
            str(ROOT / "ops/signal_latency.csv"),
            "--slo-threshold",
            "5",
            "--json-out",
            str(ROOT / "reports/signal_latency.json"),
        ]
        exit_code = run_cmd(cmd)
        if exit_code:
            return exit_code

    if args.archive_state:
        cmd = [
            sys.executable,
            str(ROOT / "scripts/archive_state.py"),
            "--runs-dir",
            str(ROOT / "runs"),
            "--output",
            str(ROOT / "ops/state_archive"),
        ]
        exit_code = run_cmd(cmd)
        if exit_code:
            return exit_code

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
