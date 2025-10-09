#!/usr/bin/env python3
"""Daily workflow orchestration script."""
from __future__ import annotations
import argparse
import csv
import math
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import partial
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Union

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.utils import yaml_compat as yaml
from scripts import ingest_providers
from scripts._time_utils import (
    parse_naive_utc as _shared_parse_naive_utc,
    utcnow_naive as _shared_utcnow_naive,
)


ProviderError = ingest_providers.ProviderError
_parse_naive_utc = _shared_parse_naive_utc
_fetch_dukascopy_records = ingest_providers.fetch_dukascopy_records
_compute_yfinance_fallback_start = ingest_providers.compute_yfinance_fallback_start
_fetch_yfinance_records = ingest_providers.fetch_yfinance_records
_raise_provider_error = ingest_providers.raise_provider_error
_mark_dukascopy_offer_side = ingest_providers.mark_dukascopy_offer_side
_YFinanceFallbackRunner = ingest_providers.YFinanceFallbackRunner


def _load_dukascopy_fetch() -> Callable[..., object]:
    """Return the Dukascopy fetch function, raising if unavailable."""

    return ingest_providers.load_dukascopy_fetch()


def _utcnow_naive() -> datetime:
    """Return the current UTC time as a naive ``datetime``."""

    return _shared_utcnow_naive(dt_cls=datetime)


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


def _resolve_path_argument(
    path_value: Optional[Union[str, Path]], *, default: Optional[Path] = None
) -> Optional[Path]:
    """Return an absolute path for user-supplied CLI arguments."""

    if path_value is None:
        return default.resolve() if isinstance(default, Path) else default

    if isinstance(path_value, str) and not path_value:
        return default.resolve() if isinstance(default, Path) else default

    candidate = Path(path_value).expanduser()
    if not candidate.is_absolute():
        candidate = (ROOT / candidate).resolve()
    else:
        candidate = candidate.resolve()

    return candidate


def _resolve_optimize_csv_path(symbol: str, bars_override: Optional[str]) -> str:
    """Return the CSV path for optimize runs, honoring overrides."""

    resolved = _resolve_path_argument(bars_override)
    if resolved is None:
        symbol_token = symbol.lower()
        resolved = (ROOT / "data" / f"{symbol_token}_5m_2018-2024_utc.csv").resolve()
    return str(resolved)


def _resolve_data_quality_outputs(
    args: argparse.Namespace,
    *,
    bars_csv: str,
) -> Dict[str, Path]:
    """Derive default output paths for the data quality audit."""

    tf_token = Path(bars_csv).stem.lower()
    symbol_lower = args.symbol.upper().lower()
    base_dir = _resolve_path_argument(
        args.data_quality_output_dir,
        default=ROOT / "reports/data_quality",
    )
    if base_dir is None:
        base_dir = (ROOT / "reports/data_quality").resolve()

    summary_path = _resolve_path_argument(
        args.data_quality_summary_json,
        default=base_dir / f"{symbol_lower}_{tf_token}_summary.json",
    )
    gap_csv_path = _resolve_path_argument(
        args.data_quality_gap_csv,
        default=base_dir / f"{symbol_lower}_{tf_token}_gap_inventory.csv",
    )
    gap_json_path = _resolve_path_argument(
        args.data_quality_gap_json,
        default=base_dir / f"{symbol_lower}_{tf_token}_gap_inventory.json",
    )

    return {
        "summary": summary_path,
        "gap_csv": gap_csv_path,
        "gap_json": gap_json_path,
    }


def _tf_to_minutes(tf: str) -> int:
    """Convert a timeframe string into minutes with defensive defaults."""

    default_minutes = 5
    if tf.endswith("m"):
        try:
            return max(1, int(tf[:-1] or default_minutes))
        except ValueError:
            return default_minutes
    if tf.endswith("h"):
        try:
            return max(1, int(tf[:-1] or 1) * 60)
        except ValueError:
            return 60
    return default_minutes


def _resolve_local_backup_path(
    *, symbol: str, backup_path: Optional[Path]
) -> Path:
    """Return the resolved CSV backup path for *symbol*."""

    from scripts import pull_prices as pull_module

    candidate_path = _resolve_path_argument(backup_path)
    if candidate_path is None:
        default_relative = pull_module.default_source_for_symbol(symbol)
        candidate_path = _resolve_path_argument(default_relative)
        if candidate_path is None or not candidate_path.exists():
            raise RuntimeError(
                "local CSV backup not found for symbol "
                f"{symbol}: expected {(ROOT / default_relative).resolve()} (override with --local-backup-csv)"
            )
        return candidate_path

    if not candidate_path.exists():
        raise RuntimeError(f"local CSV backup not found: {candidate_path}")

    return candidate_path


def _ingest_csv_source(
    *,
    ingest_records_func,
    rows: Iterable[Dict[str, object]],
    symbol: str,
    tf: str,
    snapshot_path: Path,
    raw_path: Path,
    validated_path: Path,
    features_path: Path,
    source_name: str,
    extra_kwargs: Optional[Dict[str, object]] = None,
):
    """Invoke ``ingest_records`` with consistent keyword arguments."""

    extra_kwargs = extra_kwargs or {}

    return ingest_records_func(
        rows,
        symbol=symbol,
        tf=tf,
        snapshot_path=snapshot_path,
        raw_path=raw_path,
        validated_path=validated_path,
        features_path=features_path,
        source_name=source_name,
        **extra_kwargs,
    )


def _extend_with_synthetic_bars(
    *,
    base_result: Dict[str, object],
    ingest_records_func,
    symbol: str,
    tf: str,
    snapshot_path: Path,
    raw_path: Path,
    validated_path: Path,
    features_path: Path,
    tf_minutes: int,
    now: Optional[datetime] = None,
) -> Dict[str, object]:
    """Extend *base_result* with synthetic bars when freshness lags."""

    if not isinstance(base_result, dict):
        return base_result

    last_entry = _load_last_validated_entry(validated_path)
    if last_entry is None:
        return base_result

    latest_ts = _parse_naive_utc(str(base_result.get("last_ts_now", "")))
    if latest_ts is None:
        latest_ts = last_entry["timestamp"]

    current_time = now or _utcnow_naive()
    target_end = _compute_synthetic_target(current_time, tf_minutes=tf_minutes)

    if latest_ts >= target_end:
        return base_result

    synthetic_rows = _generate_synthetic_bars(
        base_entry=last_entry,
        target_end=target_end,
        tf_minutes=tf_minutes,
        symbol=symbol,
        tf=tf,
    )

    if not synthetic_rows:
        return base_result

    synthetic_result = _ingest_csv_source(
        ingest_records_func=ingest_records_func,
        rows=synthetic_rows,
        symbol=symbol,
        tf=tf,
        snapshot_path=snapshot_path,
        raw_path=raw_path,
        validated_path=validated_path,
        features_path=features_path,
        source_name="synthetic_local",
    )

    merged = _merge_ingest_results(base_result, synthetic_result)
    return merged if merged is not None else base_result


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

    tf_minutes = _tf_to_minutes(tf)
    resolved_path = _resolve_local_backup_path(symbol=symbol, backup_path=backup_path)

    with resolved_path.open(newline="", encoding="utf-8") as fh:
        reader: Iterable[Dict[str, object]] = csv.DictReader(fh)
        result = _ingest_csv_source(
            ingest_records_func=ingest_records_func,
            rows=reader,
            symbol=symbol,
            tf=tf,
            snapshot_path=snapshot_path,
            raw_path=raw_path,
            validated_path=validated_path,
            features_path=features_path,
            source_name=f"local_csv:{resolved_path.name}",
        )

    if isinstance(result, dict):
        result.setdefault("local_backup_path", str(resolved_path))

    if not enable_synthetic:
        return result

    return _extend_with_synthetic_bars(
        base_result=result,
        ingest_records_func=ingest_records_func,
        symbol=symbol,
        tf=tf,
        snapshot_path=snapshot_path,
        raw_path=raw_path,
        validated_path=validated_path,
        features_path=features_path,
        tf_minutes=tf_minutes,
    )


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


def _execute_local_csv_fallback(
    *,
    stage: str,
    reason: str,
    fallback_notes: List[Dict[str, str]],
    trigger_reason: Optional[str] = None,
    **fallback_kwargs,
) -> Optional[Dict[str, object]]:
    """Run the local CSV fallback ingest and append structured notes."""

    message = trigger_reason or reason
    print("[wf] local CSV fallback triggered:", message)
    try:
        result = _ingest_local_csv_backup(**fallback_kwargs)
    except Exception as backup_exc:  # pragma: no cover - unexpected failure
        print(f"[wf] local CSV fallback unavailable: {backup_exc}")
        return None

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
        stage=stage,
        reason=reason,
        next_source=next_source,
        detail=detail_path,
    )

    return result


def _log_ingest_summary(result: Dict[str, object], label: str) -> None:
    """Emit a standardized ingest completion log line."""

    detail = result.get("source") if isinstance(result, dict) else None
    suffix = f" ({detail})" if detail and detail != label else ""
    print(
        f"[wf] {label}_ingest{suffix}",
        f"rows={result['rows_validated']}",
        f"last_ts={result['last_ts_now']}",
    )


def _ingest_with_provider(
    ctx: "IngestContext",
    *,
    stage: str,
    source_label: str,
    next_source: Optional[str],
    fetch_records: Callable[[], Iterable[Dict[str, object]]],
    fetch_error_prefix: Optional[str] = None,
    empty_result_reason: Optional[str] = None,
    ingest_error_prefix: Optional[str] = None,
    fallback_runner: Optional[
        Callable[[str], tuple[Optional[Dict[str, object]], Optional[str]]]
    ] = None,
    result_mutator: Optional[Callable[[Dict[str, object]], None]] = None,
    ingest_kwargs: Optional[Dict[str, Any]] = None,
) -> tuple[Optional[Dict[str, object]], Optional[str]]:
    """Execute provider fetch + ingest with shared fallback/error handling."""

    fetch_error_prefix = fetch_error_prefix or f"{stage} fetch failed"
    ingest_error_prefix = ingest_error_prefix or f"{stage} ingestion failed"
    empty_result_reason = empty_result_reason or f"{stage} fetch returned no rows"
    ingest_kwargs = ingest_kwargs or {}

    reason: Optional[str] = None
    records_list: Optional[List[Dict[str, object]]] = None

    try:
        fetched = fetch_records()
        records_list = list(fetched)
    except Exception as exc:  # pragma: no cover - defensive surface
        reason = getattr(exc, "reason", None) or f"{fetch_error_prefix}: {exc}"

    if reason is None and records_list is not None:
        if not records_list:
            reason = empty_result_reason

    if reason is None and records_list is not None:
        try:
            result = ctx.ingest_records(
                records_list,
                symbol=ctx.symbol,
                tf=ctx.tf,
                snapshot_path=ctx.snapshot_path,
                raw_path=ctx.raw_path,
                validated_path=ctx.validated_path,
                features_path=ctx.features_path,
                source_name=source_label,
                **ingest_kwargs,
            )
        except Exception as exc:
            reason = getattr(exc, "reason", None) or f"{ingest_error_prefix}: {exc}"
        else:
            if isinstance(result, dict) and result_mutator is not None:
                result_mutator(result)
            return result, source_label

    if reason is None:
        reason = f"{stage} ingestion failed"

    _append_fallback(
        ctx.fallback_notes,
        stage=stage,
        reason=reason,
        next_source=next_source,
    )

    if fallback_runner is not None:
        return fallback_runner(reason)

    fallback_result = _execute_local_csv_fallback(
        stage="local_csv",
        reason="local CSV fallback executed",
        fallback_notes=ctx.fallback_notes,
        trigger_reason=reason,
        **ctx.fallback_kwargs(),
    )
    if fallback_result is None:
        return None, None

    return fallback_result, "local_csv"


@dataclass
class IngestContext:
    """Container for shared ingest inputs and mutable fallback notes."""

    symbol: str
    tf: str
    snapshot_path: Path
    raw_path: Path
    validated_path: Path
    features_path: Path
    ingest_records: Callable[..., Dict[str, object]]
    get_last_processed_ts: Callable[..., Optional[datetime]]
    fallback_notes: List[Dict[str, str]] = field(default_factory=list)
    local_backup_path: Optional[Path] = None
    synthetic_allowed: bool = True

    def fallback_kwargs(self) -> Dict[str, Any]:
        return {
            "ingest_records_func": self.ingest_records,
            "symbol": self.symbol,
            "tf": self.tf,
            "snapshot_path": self.snapshot_path,
            "raw_path": self.raw_path,
            "validated_path": self.validated_path,
            "features_path": self.features_path,
            "backup_path": self.local_backup_path,
            "enable_synthetic": self.synthetic_allowed,
        }

    def load_last_processed_ts(self) -> Optional[datetime]:
        return self.get_last_processed_ts(
            self.symbol,
            self.tf,
            snapshot_path=self.snapshot_path,
            validated_path=self.validated_path,
        )


def _build_ingest_context(
    args: argparse.Namespace,
    *,
    local_backup_path: Optional[Path],
    synthetic_allowed: bool,
) -> IngestContext:
    from scripts.pull_prices import ingest_records, get_last_processed_ts

    symbol_upper = args.symbol.upper()
    tf = "5m"
    snapshot_path = ROOT / "ops/runtime_snapshot.json"

    return IngestContext(
        symbol=symbol_upper,
        tf=tf,
        snapshot_path=snapshot_path,
        raw_path=ROOT / "raw" / symbol_upper / f"{tf}.csv",
        validated_path=ROOT / "validated" / symbol_upper / f"{tf}.csv",
        features_path=ROOT / "features" / symbol_upper / f"{tf}.csv",
        ingest_records=ingest_records,
        get_last_processed_ts=get_last_processed_ts,
        fallback_notes=[],
        local_backup_path=local_backup_path,
        synthetic_allowed=synthetic_allowed,
    )


def _resolve_dukascopy_fetch() -> tuple[Optional[Callable[..., object]], Optional[Exception]]:
    """Return the Dukascopy fetch implementation and any initialization error."""

    return ingest_providers.resolve_dukascopy_fetch()


def _compute_dukascopy_start(
    *,
    last_ts: Optional[datetime],
    lookback_minutes: int,
    now: datetime,
) -> datetime:
    """Derive the fetch start timestamp for Dukascopy ingestion."""

    lookback = max(5, lookback_minutes)
    if last_ts:
        return last_ts - timedelta(minutes=lookback)
    return now - timedelta(minutes=lookback)



def _build_yfinance_fallback(
    ctx: IngestContext,
    args: argparse.Namespace,
    *,
    now: datetime,
    last_ts: Optional[datetime],
) -> Callable[[str], tuple[Optional[Dict[str, object]], Optional[str]]]:
    """Construct the yfinance fallback runner used by Dukascopy ingestion."""

    return _YFinanceFallbackRunner(
        ctx,
        args,
        now=now,
        last_ts=last_ts,
        ingest_runner=partial(_ingest_with_provider, ctx),
    )


def _finalize_ingest_result(
    ctx: IngestContext,
    result: Optional[Dict[str, object]],
    source_label: Optional[str],
    *,
    primary_source: str,
    empty_message: str,
) -> tuple[Optional[Dict[str, object]], int]:
    """Finalize ingest result logging and metadata persistence."""

    if result is None or not source_label:
        print(empty_message)
        return None, 1

    _log_ingest_summary(result, source_label)

    finish_now = _utcnow_naive()
    _persist_ingest_metadata(
        symbol=ctx.symbol,
        tf=ctx.tf,
        snapshot_path=ctx.snapshot_path,
        result=result,
        fallback_notes=ctx.fallback_notes,
        primary_source=primary_source,
        now=finish_now,
    )

    return result, 0


def _run_dukascopy_ingest(
    ctx: IngestContext,
    args: argparse.Namespace,
) -> tuple[Optional[Dict[str, object]], int]:
    fetch_impl, init_error = _resolve_dukascopy_fetch()

    last_ts = ctx.load_last_processed_ts()
    now = _utcnow_naive()
    start = _compute_dukascopy_start(
        last_ts=last_ts,
        lookback_minutes=args.dukascopy_lookback_minutes,
        now=now,
    )

    offer_side = (args.dukascopy_offer_side or "bid").lower()
    print(
        "[wf] fetching Dukascopy bars",
        ctx.symbol,
        ctx.tf,
        start.isoformat(timespec="seconds"),
        now.isoformat(timespec="seconds"),
        f"offer_side={offer_side}",
    )

    dukascopy_fetch = partial(
        _fetch_dukascopy_records,
        fetch_impl,
        args.symbol,
        ctx.tf,
        start=start,
        end=now,
        offer_side=offer_side,
        init_error=init_error,
        freshness_threshold=args.dukascopy_freshness_threshold_minutes,
    )

    fallback_runner = _build_yfinance_fallback(
        ctx,
        args,
        now=now,
        last_ts=last_ts,
    )

    result, source_label = _ingest_with_provider(
        ctx,
        stage="dukascopy",
        source_label="dukascopy",
        next_source="yfinance",
        fetch_records=dukascopy_fetch,
        fetch_error_prefix="fetch error",
        empty_result_reason="no rows returned",
        ingest_error_prefix="ingestion failed",
        fallback_runner=fallback_runner,
        result_mutator=partial(
            _mark_dukascopy_offer_side,
            offer_side=offer_side,
        ),
    )

    return _finalize_ingest_result(
        ctx,
        result,
        source_label,
        primary_source="dukascopy",
        empty_message="[wf] Dukascopy ingestion produced no result",
    )


def _run_yfinance_ingest(
    ctx: IngestContext,
    args: argparse.Namespace,
) -> tuple[Optional[Dict[str, object]], int]:
    last_ts = ctx.load_last_processed_ts()
    now = _utcnow_naive()

    try:
        from scripts.yfinance_fetch import fetch_bars, resolve_ticker
    except Exception as exc:
        fetch_callable = partial(
            _raise_provider_error,
            f"yfinance module unavailable: {exc}",
        )
    else:
        start = _compute_yfinance_fallback_start(
            last_ts=last_ts,
            lookback_minutes=args.yfinance_lookback_minutes,
            now=now,
        )

        fetch_symbol = resolve_ticker(ctx.symbol)
        print(
            "[wf] fetching yfinance bars",
            fetch_symbol,
            f"(source {ctx.symbol})",
            ctx.tf,
            start.isoformat(timespec="seconds"),
            now.isoformat(timespec="seconds"),
        )

        fetch_callable = partial(
            _fetch_yfinance_records,
            fetch_bars,
            args.symbol,
            ctx.tf,
            start=start,
            end=now,
            empty_reason="yfinance ingestion returned no rows",
        )

    result, source_label = _ingest_with_provider(
        ctx,
        stage="yfinance",
        source_label="yfinance",
        next_source="local_csv",
        fetch_records=fetch_callable,
        fetch_error_prefix="yfinance ingestion failed",
        empty_result_reason="yfinance ingestion returned no rows",
        ingest_error_prefix="yfinance ingestion failed during ingest",
    )

    return _finalize_ingest_result(
        ctx,
        result,
        source_label,
        primary_source="yfinance",
        empty_message="[wf] yfinance ingestion produced no result",
    )


def _run_api_ingest(
    ctx: IngestContext,
    args: argparse.Namespace,
) -> tuple[Optional[Dict[str, object]], int]:
    last_ts = ctx.load_last_processed_ts()
    now = _utcnow_naive()
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
    start = last_ts - timedelta(minutes=lookback_minutes) if last_ts else now - timedelta(minutes=lookback_minutes)

    print(
        "[wf] fetching API bars",
        ctx.symbol,
        ctx.tf,
        start.isoformat(timespec="seconds"),
        now.isoformat(timespec="seconds"),
    )

    try:
        from scripts.fetch_prices_api import fetch_prices
    except Exception as exc:  # pragma: no cover - import failure
        def _missing_api() -> Iterable[Dict[str, object]]:
            raise ProviderError(f"api ingestion failed: {exc}")

        fetch_callable = _missing_api
    else:
        def _api_fetch() -> Iterable[Dict[str, object]]:
            records = list(
                fetch_prices(
                    ctx.symbol,
                    ctx.tf,
                    start=start,
                    end=now,
                    provider=args.api_provider,
                    config_path=args.api_config,
                    credentials_path=args.api_credentials,
                )
            )
            if not records:
                raise ProviderError("api ingestion returned no rows")
            return records

        fetch_callable = _api_fetch

    result, source_label = _ingest_with_provider(
        ctx,
        stage="api",
        source_label="api",
        next_source="local_csv",
        fetch_records=fetch_callable,
        fetch_error_prefix="api ingestion failed",
        empty_result_reason="api ingestion returned no rows",
        ingest_error_prefix="api ingestion failed during ingest",
    )

    return _finalize_ingest_result(
        ctx,
        result,
        source_label,
        primary_source="api",
        empty_message="[wf] API ingestion produced no result",
    )

def run_cmd(cmd, *, cwd: Path = ROOT):
    print(f"[wf] running: {' '.join(cmd)}")
    result = subprocess.run(cmd, check=False, cwd=cwd)
    if result.returncode != 0:
        print(f"[wf] command failed with exit code {result.returncode}")
    return result.returncode


def _apply_alert_threshold_args(cmd, args):
    """Append alert threshold arguments if provided."""

    if args.alert_pips is not None:
        cmd.extend(["--alert-pips", str(args.alert_pips)])
    if args.alert_winrate is not None:
        cmd.extend(["--alert-winrate", str(args.alert_winrate)])
    if args.alert_sharpe is not None:
        cmd.extend(["--alert-sharpe", str(args.alert_sharpe)])
    if args.alert_max_drawdown is not None:
        cmd.extend(["--alert-max-drawdown", str(args.alert_max_drawdown)])


def _apply_benchmark_threshold_args(cmd, args):
    """Append benchmark performance threshold arguments if provided."""

    if args.min_sharpe is not None:
        cmd.extend(["--min-sharpe", str(args.min_sharpe)])
    if args.min_win_rate is not None:
        cmd.extend(["--min-win-rate", str(args.min_win_rate)])
    if args.max_drawdown is not None:
        cmd.extend(["--max-drawdown", str(args.max_drawdown)])


def _build_benchmark_pipeline_cmd(args, bars_csv):
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
    _apply_alert_threshold_args(cmd, args)
    _apply_benchmark_threshold_args(cmd, args)
    if args.webhook:
        cmd.extend(["--webhook", args.webhook])
    return cmd


def _build_benchmark_summary_cmd(args):
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
    _apply_benchmark_threshold_args(cmd, args)
    if args.webhook:
        cmd.extend(["--webhook", args.webhook])
    return cmd


def _build_benchmark_freshness_cmd(args):
    cmd = [
        sys.executable,
        str(ROOT / "scripts/check_benchmark_freshness.py"),
        "--snapshot",
        str(ROOT / "ops/runtime_snapshot.json"),
        "--max-age-hours",
        str(args.benchmark_freshness_base_max_age_hours),
    ]
    if args.benchmark_freshness_max_age_hours is not None:
        cmd.extend([
            "--benchmark-freshness-max-age-hours",
            str(args.benchmark_freshness_max_age_hours),
        ])
    if args.benchmark_freshness_targets:
        targets = [
            target.strip()
            for target in args.benchmark_freshness_targets.split(",")
            if target.strip()
        ]
    else:
        targets = [f"{args.symbol}:{args.mode}"]
    for target in targets:
        cmd.extend(["--target", target])
    return cmd


def _build_data_quality_cmd(args, bars_csv: str):
    outputs = _resolve_data_quality_outputs(args, bars_csv=bars_csv)
    cmd = [
        sys.executable,
        str(ROOT / "scripts/check_data_quality.py"),
        "--csv",
        bars_csv,
        "--symbol",
        args.symbol.upper(),
        "--out-json",
        str(outputs["summary"]),
        "--calendar-day-summary",
        "--calendar-day-max-report",
        str(args.data_quality_calendar_max_report),
    ]
    if args.data_quality_calendar_threshold is not None:
        cmd.extend(
            [
                "--calendar-day-coverage-threshold",
                str(args.data_quality_calendar_threshold),
            ]
        )
    if outputs["gap_csv"] is not None:
        cmd.extend(["--out-gap-csv", str(outputs["gap_csv"])])
    if outputs["gap_json"] is not None:
        cmd.extend(["--out-gap-json", str(outputs["gap_json"])])
    if args.data_quality_coverage_threshold is not None:
        cmd.extend(
            ["--fail-under-coverage", str(args.data_quality_coverage_threshold)]
        )
    cmd.append("--fail-on-calendar-day-warnings")
    return cmd


def _build_update_state_cmd(args, bars_csv):
    return [
        sys.executable,
        str(ROOT / "scripts/update_state.py"),
        "--bars",
        bars_csv,
        "--symbol",
        args.symbol,
        "--mode",
        args.mode,
        "--equity",
        str(args.equity),
        "--state-out",
        str(ROOT / "runs/active/state.json"),
    ]


def _build_optimize_cmd(args):
    optimize_csv = _resolve_optimize_csv_path(args.symbol, args.bars)
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
        optimize_csv,
        "--symbol",
        args.symbol,
        "--mode",
        args.mode,
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
        cmd.extend(["--webhook", args.webhook])
    return cmd


def _build_analyze_latency_cmd():
    return [
        sys.executable,
        str(ROOT / "scripts/analyze_signal_latency.py"),
        "--input",
        str(ROOT / "ops/signal_latency.csv"),
        "--slo-threshold",
        "5",
        "--json-out",
        str(ROOT / "reports/signal_latency.json"),
    ]


def _build_archive_state_cmd():
    return [
        sys.executable,
        str(ROOT / "scripts/archive_state.py"),
        "--runs-dir",
        str(ROOT / "runs"),
        "--output",
        str(ROOT / "ops/state_archive"),
    ]


def _build_state_health_cmd():
    return [
        sys.executable,
        str(ROOT / "scripts/check_state_health.py"),
        "--state",
        str(ROOT / "runs/active/state.json"),
        "--json-out",
        str(ROOT / "ops/health/state_checks.json"),
    ]


def _build_pull_prices_cmd(args, *, source_override: Optional[Path] = None):
    from scripts import pull_prices

    if source_override is not None:
        source_path = Path(source_override)
    else:
        source_path = _resolve_path_argument(
            pull_prices.default_source_for_symbol(args.symbol)
        )
        if source_path is None:  # pragma: no cover - defensive guard
            raise RuntimeError("unable to resolve default source CSV for pull_prices")

    return [
        sys.executable,
        str(ROOT / "scripts/pull_prices.py"),
        "--source",
        str(source_path),
        "--symbol",
        args.symbol,
    ]


_INGEST_PROVIDER_RUNNERS: Dict[str, Callable[[IngestContext, argparse.Namespace], tuple[Optional[Dict[str, object]], int]]] = {
    "dukascopy": _run_dukascopy_ingest,
    "api": _run_api_ingest,
    "yfinance": _run_yfinance_ingest,
}

_DEFAULT_CONTEXT_MESSAGES = (
    "[wf] ingestion unavailable: {exc}",
    "[wf] ingestion failed to initialize: {exc}",
)

_INGEST_CONTEXT_MESSAGES: Dict[str, tuple[str, str]] = {
    "dukascopy": (
        "[wf] Dukascopy ingestion unavailable: {exc}",
        "[wf] Dukascopy ingestion failed to initialize: {exc}",
    ),
    "yfinance": (
        "[wf] yfinance ingestion unavailable: {exc}",
        "[wf] yfinance ingestion failed to initialize pull_prices: {exc}",
    ),
    "api": (
        "[wf] API ingestion unavailable: {exc}",
        "[wf] API ingestion unavailable: {exc}",
    ),
}


def _resolve_ingest_provider(args: argparse.Namespace) -> tuple[Optional[str], int]:
    selected = [
        provider
        for provider, enabled in (
            ("dukascopy", args.use_dukascopy),
            ("api", args.use_api),
            ("yfinance", args.use_yfinance),
        )
        if enabled
    ]

    if len(selected) > 1:
        print("[wf] specify at most one of --use-dukascopy/--use-api/--use-yfinance")
        return None, 1

    return (selected[0], 0) if selected else (None, 0)


def _init_ingest_context(
    args: argparse.Namespace,
    *,
    local_backup_path: Optional[Path],
    synthetic_allowed: bool,
    provider: str,
) -> tuple[Optional[IngestContext], int]:
    runtime_msg, general_msg = _INGEST_CONTEXT_MESSAGES.get(provider, _DEFAULT_CONTEXT_MESSAGES)

    try:
        ctx = _build_ingest_context(
            args,
            local_backup_path=local_backup_path,
            synthetic_allowed=synthetic_allowed,
        )
    except RuntimeError as exc:
        print(runtime_msg.format(exc=exc))
        return None, 1
    except Exception as exc:  # pragma: no cover - defensive guard
        print(general_msg.format(exc=exc))
        return None, 1

    return ctx, 0


def _dispatch_ingest(
    args: argparse.Namespace,
    *,
    local_backup_path: Optional[Path],
    synthetic_allowed: bool,
) -> int:
    provider, status = _resolve_ingest_provider(args)
    if status:
        return status

    if provider is None:
        return run_cmd(
            _build_pull_prices_cmd(args, source_override=local_backup_path)
        )

    ctx, status = _init_ingest_context(
        args,
        local_backup_path=local_backup_path,
        synthetic_allowed=synthetic_allowed,
        provider=provider,
    )
    if status or ctx is None:
        return status

    runner = _INGEST_PROVIDER_RUNNERS.get(provider)
    if runner is None:  # pragma: no cover - unexpected wiring issue
        print(f"[wf] unsupported ingest provider: {provider}")
        return 1

    _ingest_result, exit_code = runner(ctx, args)
    return exit_code


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
        "--disable-synthetic-extension",
        action="store_true",
        help="Skip generating synthetic_local bars after local CSV fallback",
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
    parser.add_argument(
        "--check-data-quality",
        action="store_true",
        help=(
            "Audit validated bars with check_data_quality and fail when coverage or "
            "calendar-day thresholds are breached"
        ),
    )
    parser.add_argument(
        "--data-quality-output-dir",
        default=None,
        help="Directory for data quality reports (default: reports/data_quality)",
    )
    parser.add_argument(
        "--data-quality-summary-json",
        default=None,
        help=(
            "Override path for the data quality summary JSON output (default derived "
            "from symbol/timeframe)"
        ),
    )
    parser.add_argument(
        "--data-quality-gap-csv",
        default=None,
        help=(
            "Override path for the data quality gap inventory CSV (default derived "
            "from symbol/timeframe)"
        ),
    )
    parser.add_argument(
        "--data-quality-gap-json",
        default=None,
        help=(
            "Override path for the data quality gap inventory JSON (default derived "
            "from symbol/timeframe)"
        ),
    )
    parser.add_argument(
        "--data-quality-coverage-threshold",
        type=float,
        default=0.995,
        help="Minimum overall coverage ratio required before failing the audit (0-1)",
    )
    parser.add_argument(
        "--data-quality-calendar-threshold",
        type=float,
        default=0.98,
        help=(
            "Calendar-day coverage threshold used to flag warnings and trigger "
            "failures (0-1)"
        ),
    )
    parser.add_argument(
        "--data-quality-calendar-max-report",
        type=int,
        default=10,
        help="Maximum number of calendar-day entries retained in the summary",
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
        "--benchmark-freshness-base-max-age-hours",
        type=float,
        default=6.0,
        help="Max age threshold (hours) for benchmark pipeline freshness checks",
    )
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

    local_backup_path = _resolve_path_argument(args.local_backup_csv)

    symbol_input = args.symbol.upper()
    symbol_upper = symbol_input
    if symbol_input.endswith("=X"):
        fx_candidate = symbol_input[:-2]
        if len(fx_candidate) == 6 and fx_candidate.isalpha():
            symbol_upper = fx_candidate
    args.symbol = symbol_upper

    bars_path = _resolve_path_argument(
        args.bars,
        default=ROOT / f"validated/{symbol_upper}/5m.csv",
    )
    if bars_path is None:  # defensive guard; default ensures this should not happen
        raise RuntimeError("unable to resolve validated bars CSV path")
    bars_csv = str(bars_path)

    synthetic_allowed = not args.disable_synthetic_extension

    if args.data_quality_coverage_threshold is not None:
        coverage_threshold = args.data_quality_coverage_threshold
        if coverage_threshold < 0 or coverage_threshold > 1:
            raise SystemExit("--data-quality-coverage-threshold must be between 0 and 1")
    if args.data_quality_calendar_threshold is not None:
        calendar_threshold = args.data_quality_calendar_threshold
        if calendar_threshold < 0 or calendar_threshold > 1:
            raise SystemExit("--data-quality-calendar-threshold must be between 0 and 1")
    if args.data_quality_calendar_max_report < 1:
        raise SystemExit("--data-quality-calendar-max-report must be at least 1")


    if args.ingest:
        exit_code = _dispatch_ingest(
            args,
            local_backup_path=local_backup_path,
            synthetic_allowed=synthetic_allowed,
        )
        if exit_code:
            return exit_code
    mode_builders = [
        (args.check_data_quality, lambda: _build_data_quality_cmd(args, bars_csv)),
        (args.update_state, lambda: _build_update_state_cmd(args, bars_csv)),
        (args.benchmarks, lambda: _build_benchmark_pipeline_cmd(args, bars_csv)),
        (args.state_health, _build_state_health_cmd),
        (args.benchmark_summary, lambda: _build_benchmark_summary_cmd(args)),
        (args.check_benchmark_freshness, lambda: _build_benchmark_freshness_cmd(args)),
        (args.optimize, lambda: _build_optimize_cmd(args)),
        (args.analyze_latency, _build_analyze_latency_cmd),
        (args.archive_state, _build_archive_state_cmd),
    ]

    for enabled, builder in mode_builders:
        if not enabled:
            continue
        cmd = builder()
        exit_code = run_cmd(cmd)
        if exit_code:
            return exit_code

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
