"""Dashboard dataset export CLI.

This module follows the Phase 3 observability automation design by emitting
individual dashboard datasets, maintaining a manifest with monotonically
increasing sequence numbers, updating a heartbeat file, and persisting
export history with retention controls.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

if __package__ in (None, ""):
    # Allow running as a script without package context
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from analysis.dashboard import (  # noqa: E402  (import after sys.path mutation)
    EVSnapshot,
    SlippageSnapshot,
    TurnoverSnapshot,
    load_ev_history,
    load_execution_slippage,
    load_state_slippage,
    load_turnover_metrics,
)
from analysis.weekly_payload import (  # noqa: E402
    LatencyRollupEntry,
    load_latency_rollups,
)
from scripts._automation_context import build_automation_context  # noqa: E402
from scripts._automation_logging import (  # noqa: E402
    AutomationLogError,
    AutomationLogSchemaError,
    log_automation_event_with_sequence,
)
from scripts._schema import load_json_schema, validate_json_schema  # noqa: E402


DATASET_NAMES = ("ev_history", "slippage", "turnover", "latency")
DEFAULT_OUTPUT_DIR = Path("out/dashboard")
DEFAULT_HISTORY_DIR = Path("ops/dashboard_export_history")
DEFAULT_HEARTBEAT_FILE = Path("ops/dashboard_export_heartbeat.json")
DEFAULT_ARCHIVE_MANIFEST = Path("ops/dashboard_export_archive_manifest.jsonl")
DEFAULT_MANIFEST = DEFAULT_OUTPUT_DIR / "manifest.json"
DEFAULT_LATENCY_ROLLUP = Path("ops/signal_latency_rollup.csv")
DEFAULT_RETENTION_DAYS = 56


@dataclass
class DatasetResult:
    """Represents a single dataset export artefact."""

    name: str
    payload: Mapping[str, Any]
    row_count: int
    checksum_sha256: str
    path: Path
    sources: Mapping[str, str]


@dataclass
class ExportContext:
    """Resolved runtime settings for dataset export."""

    args: argparse.Namespace
    job_id: str
    generated_at: datetime
    archive_dir: Path
    runs_root: Path
    telemetry_path: Optional[Path]
    latency_path: Path
    output_dir: Path
    manifest_path: Path
    heartbeat_file: Path
    history_dir: Path
    archive_manifest: Path


@dataclass
class DatasetExportOutcome:
    """Aggregated results from dataset export builders."""

    results: List[DatasetResult]
    status: Dict[str, str]
    errors: List[Dict[str, Any]]


def _record_error(
    errors: List[Dict[str, Any]],
    dataset: str,
    error: Exception | str,
    **extra: Any,
) -> None:
    message = error if isinstance(error, str) else str(error)
    entry: Dict[str, Any] = {"dataset": dataset, "error": message}
    if extra:
        entry.update(extra)
    errors.append(entry)


def _export_selected_datasets(
    ctx: ExportContext, dataset_names: Sequence[str]
) -> DatasetExportOutcome:
    results: List[DatasetResult] = []
    status: Dict[str, str] = {}
    errors: List[Dict[str, Any]] = []
    for dataset in dataset_names:
        builder = DATASET_BUILDERS.get(dataset)
        if builder is None:
            status[dataset] = "skipped"
            continue
        try:
            result = builder(ctx)
        except Exception as exc:  # noqa: BLE001 - propagate builder failure
            status[dataset] = "error"
            _record_error(errors, dataset, exc)
        else:
            results.append(result)
            status[dataset] = "ok"
    return DatasetExportOutcome(results=results, status=status, errors=errors)


def _try_update_manifest(
    ctx: ExportContext,
    dataset_results: Sequence[DatasetResult],
    automation_payload: Mapping[str, Any],
) -> Tuple[Optional[Dict[str, Any]], Optional[Exception]]:
    try:
        manifest_entry = _update_manifest(ctx, dataset_results, automation_payload)
    except Exception as exc:  # noqa: BLE001 - convert to recoverable error
        return None, exc
    return manifest_entry, None


def _try_persist_history(
    ctx: ExportContext, dataset_results: Sequence[DatasetResult]
) -> Tuple[List[str], Optional[Exception]]:
    try:
        artefacts = _persist_history(ctx, dataset_results)
    except Exception as exc:  # noqa: BLE001 - surface retention errors to caller
        return [], exc
    return artefacts, None


def _update_heartbeat_safe(
    ctx: ExportContext,
    dataset_status: Mapping[str, str],
    generated_at: datetime,
    status: str,
    errors: Sequence[Mapping[str, Any]],
) -> Optional[Exception]:
    try:
        _update_heartbeat(ctx, dataset_status, generated_at, status, errors)
    except Exception as exc:  # noqa: BLE001 - propagate to summary handling
        return exc
    return None


def build_ev_history_dataset(ctx: ExportContext) -> DatasetResult:
    history = load_ev_history(ctx.archive_dir, limit=ctx.args.ev_limit)
    rows = [_serialise_ev_snapshot(snapshot) for snapshot in history]
    latest = rows[-1] if rows else None
    payload: Dict[str, Any] = {
        "dataset": "ev_history",
        "generated_at": _isoformat(ctx.generated_at),
        "job_id": ctx.job_id,
        "strategy": ctx.args.strategy,
        "symbol": ctx.args.symbol,
        "mode": ctx.args.mode,
        "rows": rows,
        "sources": {"archive_dir": str(ctx.archive_dir)},
    }
    if latest:
        payload["latest"] = latest
    checksum = _compute_checksum(payload, indent=ctx.args.indent)
    target = ctx.output_dir / "ev_history.json"
    _write_json_atomic(target, payload, indent=ctx.args.indent)
    return DatasetResult(
        name="ev_history",
        payload=payload,
        row_count=len(rows),
        checksum_sha256=checksum,
        path=target,
        sources={"archive_dir": str(ctx.archive_dir)},
    )


def build_slippage_dataset(ctx: ExportContext) -> DatasetResult:
    state_snapshots = load_state_slippage(ctx.archive_dir, limit=ctx.args.slip_limit)
    execution_snapshots: List[SlippageSnapshot] = []
    telemetry_sources: Dict[str, str] = {}
    if ctx.telemetry_path is not None and ctx.telemetry_path.exists():
        execution_snapshots = load_execution_slippage(ctx.telemetry_path)
        telemetry_sources["portfolio_telemetry"] = str(ctx.telemetry_path)
    payload = {
        "dataset": "slippage",
        "generated_at": _isoformat(ctx.generated_at),
        "job_id": ctx.job_id,
        "state": [_serialise_slippage_snapshot(item) for item in state_snapshots],
        "execution": [_serialise_slippage_snapshot(item) for item in execution_snapshots],
        "sources": {"archive_dir": str(ctx.archive_dir), **telemetry_sources},
    }
    row_count = len(payload["state"]) + len(payload["execution"])
    checksum = _compute_checksum(payload, indent=ctx.args.indent)
    target = ctx.output_dir / "slippage.json"
    _write_json_atomic(target, payload, indent=ctx.args.indent)
    return DatasetResult(
        name="slippage",
        payload=payload,
        row_count=row_count,
        checksum_sha256=checksum,
        path=target,
        sources=payload["sources"],
    )


def build_turnover_dataset(ctx: ExportContext) -> DatasetResult:
    turnover = load_turnover_metrics(ctx.runs_root, limit=ctx.args.turnover_limit)
    rows = [_serialise_turnover_snapshot(item) for item in turnover]
    payload = {
        "dataset": "turnover",
        "generated_at": _isoformat(ctx.generated_at),
        "job_id": ctx.job_id,
        "rows": rows,
        "sources": {"runs_root": str(ctx.runs_root)},
    }
    checksum = _compute_checksum(payload, indent=ctx.args.indent)
    target = ctx.output_dir / "turnover.json"
    _write_json_atomic(target, payload, indent=ctx.args.indent)
    return DatasetResult(
        name="turnover",
        payload=payload,
        row_count=len(rows),
        checksum_sha256=checksum,
        path=target,
        sources=payload["sources"],
    )


def build_latency_dataset(ctx: ExportContext) -> DatasetResult:
    if not ctx.latency_path.exists():
        raise FileNotFoundError(f"Latency rollup file not found: {ctx.latency_path}")
    entries = load_latency_rollups(ctx.latency_path)
    if ctx.args.latency_limit is not None and ctx.args.latency_limit >= 0:
        entries = entries[-ctx.args.latency_limit :]
    rows = [_serialise_latency_entry(item) for item in entries]
    payload = {
        "dataset": "latency",
        "generated_at": _isoformat(ctx.generated_at),
        "job_id": ctx.job_id,
        "rows": rows,
        "sources": {"latency_rollup": str(ctx.latency_path)},
    }
    checksum = _compute_checksum(payload, indent=ctx.args.indent)
    target = ctx.output_dir / "latency.json"
    _write_json_atomic(target, payload, indent=ctx.args.indent)
    return DatasetResult(
        name="latency",
        payload=payload,
        row_count=len(rows),
        checksum_sha256=checksum,
        path=target,
        sources=payload["sources"],
    )


DATASET_BUILDERS = {
    "ev_history": build_ev_history_dataset,
    "slippage": build_slippage_dataset,
    "turnover": build_turnover_dataset,
    "latency": build_latency_dataset,
}


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export observability dashboard datasets.")
    parser.add_argument("--runs-root", default="runs", help="Root directory containing run outputs.")
    parser.add_argument(
        "--state-archive-root",
        default="ops/state_archive",
        help="Root directory containing EV state archives.",
    )
    parser.add_argument("--archive-dir", help="Explicit EV archive directory (overrides strategy/symbol/mode).")
    parser.add_argument("--strategy", default="day_orb_5m.DayORB5m", help="Strategy identifier for archive resolution.")
    parser.add_argument("--symbol", default="USDJPY", help="Symbol for archive resolution.")
    parser.add_argument("--mode", default="conservative", help="Mode for archive resolution.")
    parser.add_argument("--portfolio-telemetry", help="Path to router telemetry JSON for execution slippage.")
    parser.add_argument("--ev-limit", type=int, default=120, help="Maximum EV snapshots to include (None for all).")
    parser.add_argument("--slip-limit", type=int, default=60, help="Maximum slippage snapshots to include (None for all).")
    parser.add_argument("--turnover-limit", type=int, default=50, help="Maximum turnover rows to include (None for all).")
    parser.add_argument("--latency-rollup", default=str(DEFAULT_LATENCY_ROLLUP), help="Path to latency rollup CSV.")
    parser.add_argument("--latency-limit", type=int, default=168, help="Maximum latency rows to include (None for all).")
    parser.add_argument("--dataset", action="append", choices=DATASET_NAMES, help="Datasets to export.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for dataset JSON artefacts.")
    parser.add_argument(
        "--manifest",
        default=str(DEFAULT_MANIFEST),
        help="Path to manifest JSON describing exported datasets.",
    )
    parser.add_argument(
        "--heartbeat-file",
        default=str(DEFAULT_HEARTBEAT_FILE),
        help="Heartbeat JSON file tracking export status.",
    )
    parser.add_argument(
        "--history-dir",
        default=str(DEFAULT_HISTORY_DIR),
        help="Directory used to persist historical exports for auditing.",
    )
    parser.add_argument(
        "--archive-manifest",
        default=str(DEFAULT_ARCHIVE_MANIFEST),
        help="Manifest capturing archived history bundles.",
    )
    parser.add_argument(
        "--history-retention-days",
        type=int,
        default=DEFAULT_RETENTION_DAYS,
        help="Retention window for history exports in days.",
    )
    parser.add_argument("--provenance", help="Optional JSON file providing additional provenance metadata.")
    parser.add_argument("--upload-command", help="Optional shell command executed after export succeeds.")
    parser.add_argument("--job-name", default="dashboard-export", help="Automation job name for logging.")
    parser.add_argument("--job-id", help="Explicit job identifier override.")
    parser.add_argument("--config", help="Path to configuration file (recorded in automation context).")
    parser.add_argument(
        "--json-out",
        dest="json_out",
        help="Optional path to write summary metadata about the export run.",
    )
    parser.add_argument("--indent", type=int, default=2, help="Indent level for JSON outputs.")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    ctx = build_automation_context(
        args.job_name,
        job_id=args.job_id,
        config_path=args.config,
        argv=list(argv) if argv is not None else sys.argv,
    )

    datasets = list(args.dataset or DATASET_NAMES)
    generated_at = datetime.now(timezone.utc)
    export_ctx = _build_export_context(args, ctx.job_id, generated_at)

    export_ctx.output_dir.mkdir(parents=True, exist_ok=True)

    dataset_outcome = _export_selected_datasets(export_ctx, datasets)
    dataset_results = dataset_outcome.results
    dataset_status = dataset_outcome.status
    errors = list(dataset_outcome.errors)

    status = "ok" if not errors else "error"
    artefacts: List[str] = [str(result.path) for result in dataset_results]
    manifest_entry: Optional[Dict[str, Any]] = None

    if dataset_results:
        manifest_entry, manifest_error = _try_update_manifest(
            export_ctx, dataset_results, ctx.as_log_payload()
        )
        if manifest_entry is not None:
            artefacts.append(str(export_ctx.manifest_path))
        elif manifest_error is not None:
            status = "error"
            _record_error(errors, "manifest", manifest_error)

    history_paths, history_error = _try_persist_history(export_ctx, dataset_results)
    if history_error is not None:
        status = "error"
        _record_error(errors, "history", history_error)
    else:
        artefacts.extend(history_paths)

    heartbeat_error: Optional[Dict[str, Any]] = None

    upload_result: Optional[Dict[str, Any]] = None
    if args.upload_command:
        upload_args = shlex.split(args.upload_command)
        if status == "ok":
            try:
                upload_result = _run_upload_command(args.upload_command)
            except subprocess.CalledProcessError as exc:  # noqa: PERF203 - explicit failure capture
                status = "error"
                upload_result = {
                    "command": upload_args,
                    "returncode": exc.returncode,
                    "stdout": exc.stdout,
                    "stderr": exc.stderr,
                }
                _record_error(errors, "upload", "upload_failed", returncode=exc.returncode)
        else:
            upload_result = {"command": upload_args, "skipped": True}

    heartbeat_exc = _update_heartbeat_safe(export_ctx, dataset_status, generated_at, status, errors)
    if heartbeat_exc is None:
        artefacts.append(str(export_ctx.heartbeat_file))
    else:
        status = "error"
        heartbeat_error = {"error": str(heartbeat_exc)}
        _record_error(errors, "heartbeat", heartbeat_exc)

    summary = {
        "status": status,
        "job_id": ctx.job_id,
        "generated_at": _isoformat(generated_at),
        "datasets": dataset_status,
        "artefacts": artefacts,
        "sequence": manifest_entry.get("sequence") if manifest_entry else None,
        "errors": errors,
    }
    if manifest_entry:
        summary["manifest"] = manifest_entry
    if heartbeat_error:
        summary["heartbeat_error"] = heartbeat_error
    if upload_result is not None:
        summary["upload"] = upload_result

    _write_optional_json(args.json_out, summary)

    try:
        log_automation_event_with_sequence(
            ctx.job_id,
            status,
            artefacts=artefacts,
            diagnostics={"errors": errors} if errors else None,
            extra={"automation": ctx.as_log_payload()},
        )
    except (AutomationLogError, AutomationLogSchemaError) as exc:
        summary["logging_error"] = str(exc)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if status == "ok" else 1


def _build_export_context(args: argparse.Namespace, job_id: str, generated_at: datetime) -> ExportContext:
    archive_dir = _resolve_archive_dir(args)
    runs_root = Path(args.runs_root).resolve()
    telemetry_path = Path(args.portfolio_telemetry).resolve() if args.portfolio_telemetry else None
    latency_path = Path(args.latency_rollup).resolve()
    output_dir = Path(args.output_dir).resolve()
    manifest_path = Path(args.manifest).resolve()
    heartbeat_file = Path(args.heartbeat_file).resolve()
    history_dir = Path(args.history_dir).resolve()
    archive_manifest = Path(args.archive_manifest).resolve()
    return ExportContext(
        args=args,
        job_id=job_id,
        generated_at=generated_at,
        archive_dir=archive_dir,
        runs_root=runs_root,
        telemetry_path=telemetry_path,
        latency_path=latency_path,
        output_dir=output_dir,
        manifest_path=manifest_path,
        heartbeat_file=heartbeat_file,
        history_dir=history_dir,
        archive_manifest=archive_manifest,
    )


def _resolve_archive_dir(args: argparse.Namespace) -> Path:
    if args.archive_dir:
        return Path(args.archive_dir).resolve()
    base = Path(args.state_archive_root).resolve()
    return base / args.strategy / args.symbol / args.mode


def _serialise_ev_snapshot(snapshot: EVSnapshot) -> Dict[str, Any]:
    payload = snapshot.to_dict()
    payload["timestamp"] = _isoformat(snapshot.timestamp)
    return payload


def _serialise_slippage_snapshot(snapshot: SlippageSnapshot) -> Dict[str, Any]:
    payload = snapshot.to_dict()
    payload["timestamp"] = _isoformat(snapshot.timestamp)
    return payload


def _serialise_turnover_snapshot(snapshot: TurnoverSnapshot) -> Dict[str, Any]:
    payload = snapshot.to_dict()
    payload["timestamp"] = _isoformat(snapshot.timestamp)
    return payload


def _serialise_latency_entry(entry: LatencyRollupEntry) -> Dict[str, Any]:
    return {
        "window_start": _isoformat(entry.window_start),
        "window_end": _isoformat(entry.window_end),
        "count": entry.count,
        "failure_count": entry.failure_count,
        "failure_rate": entry.failure_rate,
        "p50_ms": entry.p50_ms,
        "p95_ms": entry.p95_ms,
        "p99_ms": entry.p99_ms,
        "max_ms": entry.max_ms,
        "breach_flag": entry.breach_flag,
        "breach_streak": entry.breach_streak,
    }


def _compute_checksum(payload: Mapping[str, Any], *, indent: int) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _write_json_atomic(path: Path, payload: Mapping[str, Any], *, indent: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, ensure_ascii=False, indent=indent) + "\n"
    with tempfile.NamedTemporaryFile("w", delete=False, dir=str(path.parent), encoding="utf-8") as handle:
        handle.write(data)
        temp_path = Path(handle.name)
    os.replace(temp_path, path)


def _update_manifest(
    ctx: ExportContext,
    dataset_results: Sequence[DatasetResult],
    automation_payload: Mapping[str, Any],
) -> Dict[str, Any]:
    lock_path = ctx.manifest_path.with_suffix(ctx.manifest_path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            try:
                previous = _read_json(ctx.manifest_path)
                previous_sequence = int(previous.get("sequence", 0)) if isinstance(previous, Mapping) else 0
            except Exception:
                previous_sequence = 0
            sequence = previous_sequence + 1
            provenance = _build_provenance(ctx, automation_payload)
            dataset_entries = [
                {
                    "dataset": result.name,
                    "path": str(result.path),
                    "checksum_sha256": result.checksum_sha256,
                    "row_count": result.row_count,
                    "generated_at": _isoformat(ctx.generated_at),
                    "source_hash": _hash_sources(result.sources),
                }
                for result in dataset_results
            ]
            manifest_payload: Dict[str, Any] = {
                "sequence": sequence,
                "generated_at": _isoformat(ctx.generated_at),
                "job_id": ctx.job_id,
                "datasets": dataset_entries,
                "provenance": provenance,
            }
            _validate_manifest(manifest_payload)
            _write_json_atomic(ctx.manifest_path, manifest_payload, indent=ctx.args.indent)
            return manifest_payload
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def _build_provenance(ctx: ExportContext, automation_payload: Mapping[str, Any]) -> Dict[str, Any]:
    input_paths = {str(ctx.archive_dir), str(ctx.runs_root), str(ctx.latency_path)}
    if ctx.telemetry_path:
        input_paths.add(str(ctx.telemetry_path))
    provenance: Dict[str, Any] = {
        "command": automation_payload.get("command") or "",
        "commit_sha": automation_payload.get("commit_sha") or "unknown",
        "inputs": sorted(input_paths),
    }
    if ctx.args.provenance:
        extra = _read_json(Path(ctx.args.provenance))
        if isinstance(extra, Mapping):
            for key, value in extra.items():
                if key == "inputs" and isinstance(value, Iterable):
                    combined = set(provenance.get("inputs", []))
                    combined.update(str(item) for item in value)
                    provenance["inputs"] = sorted(combined)
                else:
                    provenance[key] = value
    return provenance


def _validate_manifest(payload: Mapping[str, Any]) -> None:
    schema_path = Path("schemas/dashboard_manifest.schema.json")
    schema = load_json_schema(schema_path)
    validate_json_schema(payload, schema)


def _persist_history(ctx: ExportContext, dataset_results: Sequence[DatasetResult]) -> List[str]:
    ctx.history_dir.mkdir(parents=True, exist_ok=True)
    export_dir = ctx.history_dir / ctx.job_id
    export_dir.mkdir(parents=True, exist_ok=True)
    artefacts: List[str] = []
    index_entries: List[Dict[str, Any]] = []
    for result in dataset_results:
        target = export_dir / result.path.name
        shutil.copy2(result.path, target)
        artefacts.append(str(target))
        index_entries.append(
            {
                "dataset": result.name,
                "path": str(target),
                "checksum_sha256": result.checksum_sha256,
                "row_count": result.row_count,
            }
        )
    history_manifest = {
        "job_id": ctx.job_id,
        "generated_at": _isoformat(ctx.generated_at),
        "datasets": index_entries,
    }
    history_manifest_path = export_dir / "manifest.json"
    _write_json_atomic(history_manifest_path, history_manifest, indent=ctx.args.indent)
    artefacts.append(str(history_manifest_path))
    _apply_history_retention(ctx)
    return artefacts


def _apply_history_retention(ctx: ExportContext) -> None:
    if ctx.args.history_retention_days is None or ctx.args.history_retention_days < 0:
        return
    threshold = datetime.now(timezone.utc) - timedelta(days=ctx.args.history_retention_days)
    for subdir in ctx.history_dir.iterdir():
        if not subdir.is_dir():
            continue
        job_timestamp = _parse_job_timestamp(subdir.name)
        if job_timestamp is None or job_timestamp >= threshold:
            continue
        archived = {
            "job_id": subdir.name,
            "archived_at": _isoformat(datetime.now(timezone.utc)),
            "datasets": sorted(str(path.name) for path in subdir.glob("*.json")),
        }
        _append_archive_manifest(ctx.archive_manifest, archived)
        shutil.rmtree(subdir, ignore_errors=True)


def _append_archive_manifest(path: Path, entry: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _update_heartbeat(
    ctx: ExportContext,
    dataset_status: Mapping[str, str],
    generated_at: datetime,
    status: str,
    errors: Sequence[Mapping[str, Any]],
) -> None:
    heartbeat: MutableMapping[str, Any] = {}
    if ctx.heartbeat_file.exists():
        existing = _read_json(ctx.heartbeat_file)
        if isinstance(existing, Mapping):
            heartbeat.update(existing)
    heartbeat.update(
        {
            "job_id": ctx.job_id,
            "generated_at": _isoformat(generated_at),
            "datasets": dict(dataset_status),
        }
    )
    if status == "ok":
        heartbeat["last_success_at"] = _isoformat(generated_at)
        heartbeat.pop("last_failure", None)
    else:
        heartbeat["last_failure"] = {
            "at": _isoformat(generated_at),
            "job_id": ctx.job_id,
            "errors": list(errors),
        }
    _write_json_atomic(ctx.heartbeat_file, heartbeat, indent=ctx.args.indent)


def _run_upload_command(command: str) -> Dict[str, Any]:
    args = shlex.split(command)
    result = subprocess.run(args, capture_output=True, text=True, check=True)
    return {
        "command": args,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _hash_sources(sources: Mapping[str, str]) -> str:
    canonical = json.dumps(dict(sorted(sources.items())), separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _read_json(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(str(path))
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_optional_json(path: Optional[str], payload: Mapping[str, Any]) -> None:
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, ensure_ascii=False, indent=2)
    target.write_text(data, encoding="utf-8")


def _isoformat(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_job_timestamp(job_id: str) -> Optional[datetime]:
    parts = job_id.split("-")
    if not parts:
        return None
    prefix = parts[0]
    try:
        return datetime.strptime(prefix, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


if __name__ == "__main__":
    raise SystemExit(main())
