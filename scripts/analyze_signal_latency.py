"""Signal latency sampling automation CLI."""
from __future__ import annotations

import argparse
import csv
import fcntl
import gzip
import hashlib
import json
import os
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple

from analysis.latency_rollup import LatencyRollup, LatencySample, aggregate
from core.utils import yaml_compat as yaml
from scripts._automation_context import AutomationContext, build_automation_context
from scripts._automation_logging import AutomationLogError, log_automation_event_with_sequence
from scripts._schema import SchemaValidationError, load_json_schema, validate_json_schema

RAW_FIELDNAMES = ["timestamp_utc", "latency_ms", "status", "detail", "source"]
ROLLUP_FIELDNAMES = [
    "hour_utc",
    "window_end_utc",
    "count",
    "failure_count",
    "failure_rate",
    "p50_ms",
    "p95_ms",
    "p99_ms",
    "max_ms",
    "breach_flag",
    "breach_streak",
]
DEFAULT_ALERT_CONFIG = {
    "slo_p95_ms": 5000,
    "warning_threshold": 2,
    "critical_threshold": 3,
    "failure_rate_threshold": 0.01,
}
DEFAULT_MAX_RAW_BYTES = 10 * 1024 * 1024
REPO_ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_SCHEMA_PATH = REPO_ROOT / "schemas/signal_latency_archive.schema.json"


@dataclass
class RawRecord:
    timestamp: datetime
    latency_ms: float
    status: str
    detail: Optional[str] = None
    source: Optional[str] = None

    def to_row(self) -> Dict[str, Any]:
        return {
            "timestamp_utc": _format_ts(self.timestamp),
            "latency_ms": f"{self.latency_ms:.6f}",
            "status": self.status,
            "detail": self.detail or "",
            "source": self.source or "",
        }

    def to_sample(self) -> LatencySample:
        return LatencySample(
            timestamp=self.timestamp,
            latency_ms=self.latency_ms,
            status=self.status,
            detail=self.detail,
            source=self.source,
        )


@dataclass
class AlertConfig:
    slo_p95_ms: float
    warning_threshold: int
    critical_threshold: int
    failure_rate_threshold: float


@dataclass
class AlertPayload:
    severity: str
    message: str
    breach_range: str
    evidence_path: str
    alert_id: str

    def as_log_entry(self) -> Dict[str, Any]:
        return {
            "id": self.alert_id,
            "severity": self.severity,
            "message": self.message,
            "breach_range": self.breach_range,
            "evidence_path": self.evidence_path,
        }

    def as_json(self) -> Dict[str, Any]:
        payload = self.as_log_entry()
        payload["schema_version"] = "2026-06-29"
        return payload


class LockNotAcquired(RuntimeError):
    """Raised when the automation lock cannot be obtained."""


@dataclass
class _LockHandle:
    file: Any
    path: Path
    acquired_at: float
    latency_ms: float

    def release(self) -> None:
        fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
        self.file.close()


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze and rotate signal latency artefacts")
    parser.add_argument("--input", default="ops/signal_latency.csv", help="Raw latency CSV path")
    parser.add_argument(
        "--rollup-output",
        default="ops/signal_latency_rollup.csv",
        help="Aggregated rollup CSV output",
    )
    parser.add_argument(
        "--raw-retention-days",
        type=int,
        default=14,
        help="Days of raw samples to retain before pruning",
    )
    parser.add_argument(
        "--rollup-retention-days",
        type=int,
        default=90,
        help="Days of rollup history to retain",
    )
    parser.add_argument(
        "--lock-file",
        default="ops/.latency.lock",
        help="Lock file used to prevent concurrent executions",
    )
    parser.add_argument(
        "--alert-config",
        default="configs/observability/latency_alert.yaml",
        help="Alert configuration YAML file",
    )
    parser.add_argument(
        "--max-raw-bytes",
        type=int,
        default=DEFAULT_MAX_RAW_BYTES,
        help="Rotate raw CSV once the file exceeds this size",
    )
    parser.add_argument(
        "--archive-dir",
        default="ops/signal_latency_archive",
        help="Directory for rotated raw latency archives",
    )
    parser.add_argument(
        "--archive-manifest",
        default="ops/signal_latency_archive/manifest.jsonl",
        help="Manifest file tracking rotated archives",
    )
    parser.add_argument(
        "--heartbeat-file",
        default="ops/latency_job_heartbeat.json",
        help="Heartbeat JSON capturing latest job status",
    )
    parser.add_argument(
        "--dry-run-alert",
        action="store_true",
        help="Write alert payloads to out/latency_alerts without sending webhooks",
    )
    parser.add_argument(
        "--alerts-dir",
        default="out/latency_alerts",
        help="Directory for dry-run alert payloads",
    )
    parser.add_argument(
        "--slo-threshold",
        type=float,
        default=None,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--failure-threshold",
        type=float,
        default=None,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--out-json",
        dest="out_json",
        default=None,
        help="Optional summary JSON output path",
    )
    parser.add_argument(
        "--json-out",
        dest="out_json",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--job-name",
        default="latency",
        help="Job name used when generating automation log entries",
    )
    parser.add_argument(
        "--job-id",
        default=None,
        help="Explicit job identifier override",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    ctx = build_automation_context(
        args.job_name,
        job_id=args.job_id,
        config_path=args.alert_config,
        argv=list(argv) if argv is not None else sys.argv,
    )
    start = time.perf_counter()
    try:
        with _acquire_lock(Path(args.lock_file)) as lock_handle:
            summary, alerts, artefacts, status = _execute_job(args, ctx, lock_handle.latency_ms)
            summary["duration_ms"] = round((time.perf_counter() - start) * 1000, 3)
            _persist_outputs(args, summary)
            _log_completion(ctx, status, summary, alerts, artefacts)
            print(json.dumps(summary, ensure_ascii=False))
            return 0
    except LockNotAcquired:
        message = "lock_not_acquired"
        summary = {
            "status": "skipped",
            "reason": message,
            "lock_file": str(Path(args.lock_file)),
        }
        _persist_outputs(args, summary)
        _log_completion(
            ctx,
            "skipped",
            summary,
            [],
            [],
            diagnostics={"error_code": message},
        )
        print(json.dumps(summary, ensure_ascii=False))
        return 0
    except Exception as exc:  # pragma: no cover - defensive guard
        diagnostics = {"error_code": type(exc).__name__, "error_message": str(exc)}
        summary = {
            "status": "error",
            "message": str(exc),
        }
        _persist_outputs(args, summary)
        _log_completion(ctx, "error", summary, [], [], diagnostics=diagnostics)
        print(json.dumps(summary, ensure_ascii=False))
        return 1


def _execute_job(
    args: argparse.Namespace,
    ctx: AutomationContext,
    lock_latency_ms: float,
) -> Tuple[Dict[str, Any], List[AlertPayload], List[str], str]:
    now = datetime.now(timezone.utc)
    raw_path = Path(args.input)
    rollup_path = Path(args.rollup_output)
    archive_dir = Path(args.archive_dir)
    manifest_path = Path(args.archive_manifest)
    heartbeat_path = Path(args.heartbeat_file)

    raw_records = _load_raw_records(raw_path)
    raw_cutoff = now - timedelta(days=max(args.raw_retention_days, 0))
    retained_records = [record for record in raw_records if record.timestamp >= raw_cutoff]
    records_for_rollup = list(retained_records)

    _write_raw_records(raw_path, retained_records)
    rotation_entry = None
    stored_records = retained_records
    if raw_path.exists() and raw_path.stat().st_size > max(args.max_raw_bytes, 0):
        rotation_entry = _rotate_raw_file(
            raw_path,
            archive_dir,
            manifest_path,
            ctx.job_id,
            retained_records,
        )
        stored_records = []
        _write_raw_records(raw_path, stored_records)

    alert_config = _load_alert_config(args)
    new_rollups = aggregate(record.to_sample() for record in records_for_rollup)
    existing_rollups = _load_rollup_rows(rollup_path)
    merged_rollups = _merge_rollups(existing_rollups, new_rollups)
    rollup_cutoff = now - timedelta(days=max(args.rollup_retention_days, 0))
    merged_rollups = [rollup for rollup in merged_rollups if rollup.window_end >= rollup_cutoff]
    annotated_rollups = _annotate_rollups(merged_rollups, alert_config)
    heartbeat = _load_heartbeat(heartbeat_path)
    previous_streak = int(heartbeat.get("breach_streak", 0) or 0)
    if annotated_rollups:
        latest_rollup = annotated_rollups[-1]
        if latest_rollup.breach_flag:
            breach_streak = previous_streak + 1
        else:
            breach_streak = 0
        annotated_rollups[-1] = replace(latest_rollup, breach_streak=breach_streak)
        latest_rollup = annotated_rollups[-1]
    else:
        latest_rollup = None
        breach_streak = 0
    _write_rollups(rollup_path, annotated_rollups)
    alerts: List[AlertPayload] = []
    severity: Optional[str] = None
    if latest_rollup:
        if latest_rollup.failure_rate > alert_config.failure_rate_threshold:
            severity = "warning"
        if latest_rollup.breach_streak >= alert_config.critical_threshold:
            severity = "critical"
        elif latest_rollup.breach_streak >= alert_config.warning_threshold:
            severity = severity or "warning"
        if severity:
            message = (
                f"p95 latency {latest_rollup.p95_ms:.1f}ms "
                f"(threshold {alert_config.slo_p95_ms:.1f}ms); "
                f"failure_rate {latest_rollup.failure_rate:.4f}"
            )
            alerts.append(
                AlertPayload(
                    severity=severity,
                    message=message,
                    breach_range=f"last {max(1, latest_rollup.breach_streak)} samples",
                    evidence_path=str(rollup_path),
                    alert_id=f"latency-breach-{ctx.job_id}",
                )
            )

    if args.dry_run_alert and alerts:
        _write_dry_run_alerts(Path(args.alerts_dir), ctx.job_id, alerts)

    heartbeat_payload = {
        "job_id": ctx.job_id,
        "status": "warning" if alerts else "ok",
        "last_success_at": _format_ts(now),
        "breach_streak": breach_streak,
        "pending_alerts": len(alerts),
    }
    if alerts:
        heartbeat_payload["last_breach_at"] = _format_ts(now)
    _write_json_atomic(heartbeat_path, heartbeat_payload)

    artefacts = [str(raw_path), str(rollup_path), str(heartbeat_path)]
    if rotation_entry is not None:
        artefacts.append(rotation_entry["path"])
        artefacts.append(str(manifest_path))

    summary = {
        "status": "dry_run" if args.dry_run_alert else ("warning" if alerts else "ok"),
        "samples_analyzed": len(records_for_rollup),
        "samples_retained": len(stored_records),
        "rollups_total": len(annotated_rollups),
        "breach_count": sum(1 for rollup in annotated_rollups if rollup.breach_flag),
        "breach_streak": breach_streak,
        "lock_latency_ms": round(lock_latency_ms, 3),
        "next_rotation_bytes": max(0, max(args.max_raw_bytes, 0) - raw_path.stat().st_size),
        "job_id": ctx.job_id,
    }
    if latest_rollup:
        summary["latest_p95_ms"] = round(latest_rollup.p95_ms, 3)
        summary["latest_failure_rate"] = round(latest_rollup.failure_rate, 6)
    if rotation_entry is not None:
        summary["rotated"] = rotation_entry

    status = summary["status"]
    return summary, alerts, artefacts, status


def _persist_outputs(args: argparse.Namespace, summary: Mapping[str, Any]) -> None:
    if args.out_json:
        Path(args.out_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out_json).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _log_completion(
    ctx: AutomationContext,
    status: str,
    summary: Mapping[str, Any],
    alerts: Sequence[AlertPayload],
    artefacts: Sequence[str],
    diagnostics: Optional[Mapping[str, Any]] = None,
) -> None:
    try:
        log_automation_event_with_sequence(
            ctx.job_id,
            status,
            duration_ms=int(summary.get("duration_ms", 0)),
            attempts=1,
            artefacts=artefacts,
            alerts=[alert.as_log_entry() for alert in alerts],
            diagnostics=diagnostics,
            extra={"summary": dict(summary)},
        )
    except AutomationLogError:
        # Logging failures should not crash the job execution path.
        pass


@contextmanager
def _acquire_lock(path: Path) -> Iterator[_LockHandle]:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+")
    start = time.perf_counter()
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        handle.close()
        raise LockNotAcquired(str(exc)) from exc
    latency_ms = (time.perf_counter() - start) * 1000
    lock = _LockHandle(file=handle, path=path, acquired_at=start, latency_ms=latency_ms)
    try:
        yield lock
    finally:
        lock.release()


def _load_raw_records(path: Path) -> List[RawRecord]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        records: List[RawRecord] = []
        for row in reader:
            record = _parse_raw_row(row)
            if record is not None:
                records.append(record)
        return records


def _parse_raw_row(row: Mapping[str, Any]) -> Optional[RawRecord]:
    try:
        if "timestamp_utc" in row and "latency_ms" in row:
            timestamp = _parse_ts(row["timestamp_utc"])
            latency_ms = float(row.get("latency_ms", 0.0))
            status = (row.get("status") or "success").strip() or "success"
            return RawRecord(
                timestamp=timestamp,
                latency_ms=latency_ms,
                status=status,
                detail=(row.get("detail") or "").strip() or None,
                source=(row.get("source") or "").strip() or None,
            )
        if "ts_emit" in row and "ts_ack" in row:
            emit = _parse_ts(row["ts_emit"])
            ack = _parse_ts(row["ts_ack"])
            latency_ms = max((ack - emit).total_seconds() * 1000.0, 0.0)
            status = (row.get("status") or "success").strip() or "success"
            return RawRecord(
                timestamp=ack,
                latency_ms=latency_ms,
                status=status,
                detail=(row.get("detail") or "").strip() or None,
                source=(row.get("signal_id") or "").strip() or None,
            )
    except Exception:
        return None
    return None


def _write_raw_records(path: Path, records: Sequence[RawRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=RAW_FIELDNAMES)
        writer.writeheader()
        for record in records:
            writer.writerow(record.to_row())


def _load_rollup_rows(path: Path) -> List[LatencyRollup]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rollups: List[LatencyRollup] = []
        for row in reader:
            try:
                window_start = _parse_ts(row["hour_utc"])
                window_end_text = (row.get("window_end_utc") or "").strip()
                if window_end_text:
                    window_end = _parse_ts(window_end_text)
                else:
                    window_end = window_start + timedelta(hours=1)
                breach_flag = _parse_bool(row.get("breach_flag"))
                breach_streak = int(float(row.get("breach_streak", 0) or 0))
                rollups.append(
                    LatencyRollup(
                        window_start=window_start,
                        window_end=window_end,
                        count=int(row.get("count", 0) or 0),
                        failure_count=int(row.get("failure_count", 0) or 0),
                        p50_ms=float(row.get("p50_ms", 0.0) or 0.0),
                        p95_ms=float(row.get("p95_ms", 0.0) or 0.0),
                        p99_ms=float(row.get("p99_ms", 0.0) or 0.0),
                        max_ms=float(row.get("max_ms", 0.0) or 0.0),
                        breach_flag=breach_flag,
                        breach_streak=breach_streak,
                    )
                )
            except Exception:
                continue
        return sorted(rollups, key=lambda item: item.window_start)


def _merge_rollups(
    existing: Sequence[LatencyRollup],
    new_rollups: Sequence[LatencyRollup],
) -> List[LatencyRollup]:
    rollup_map: Dict[datetime, LatencyRollup] = {item.window_start: item for item in existing}
    for rollup in new_rollups:
        rollup_map[rollup.window_start] = rollup
    return sorted(rollup_map.values(), key=lambda item: item.window_start)


def _annotate_rollups(
    rollups: Sequence[LatencyRollup],
    alert_config: AlertConfig,
) -> List[LatencyRollup]:
    streak = 0
    annotated: List[LatencyRollup] = []
    for rollup in sorted(rollups, key=lambda item: item.window_start):
        breach = rollup.p95_ms > alert_config.slo_p95_ms or (
            rollup.failure_rate > alert_config.failure_rate_threshold
        )
        if breach:
            streak += 1
        else:
            streak = 0
        annotated.append(replace(rollup, breach_flag=breach, breach_streak=streak))
    return annotated


def _write_rollups(path: Path, rollups: Sequence[LatencyRollup]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=ROLLUP_FIELDNAMES)
        writer.writeheader()
        for rollup in rollups:
            writer.writerow(rollup.as_csv_row())


def _rotate_raw_file(
    path: Path,
    archive_dir: Path,
    manifest_path: Path,
    job_id: str,
    retained_records: Sequence[RawRecord],
) -> Dict[str, Any]:
    archive_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc)
    archive_subdir = archive_dir / timestamp.strftime("%Y") / timestamp.strftime("%m")
    archive_subdir.mkdir(parents=True, exist_ok=True)
    archive_name = f"{job_id}.csv.gz"
    archive_path = archive_subdir / archive_name
    with path.open("rb") as source, gzip.open(archive_path, "wb") as target:
        target.write(source.read())
    sha256 = _compute_sha256(archive_path)
    manifest_entry = {
        "job_id": job_id,
        "path": str(archive_path),
        "sha256": sha256,
        "row_count": len(retained_records),
        "rotated_at": _format_ts(timestamp),
    }
    _append_manifest(manifest_path, manifest_entry)
    return manifest_entry


def _append_manifest(path: Path, entry: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _validate_manifest_entry(entry)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _load_alert_config(args: argparse.Namespace) -> AlertConfig:
    config_path = Path(args.alert_config)
    config: Dict[str, Any] = {}
    if config_path.exists():
        text = config_path.read_text(encoding="utf-8")
        loaded = yaml.safe_load(text) or {}
        if isinstance(loaded, Mapping):
            config.update(loaded)
    slo_ms = float(config.get("slo_p95_ms", DEFAULT_ALERT_CONFIG["slo_p95_ms"]))
    if "slo_threshold" in config:
        slo_ms = float(config["slo_threshold"]) * 1000.0
    if args.slo_threshold is not None:
        slo_ms = float(args.slo_threshold) * 1000.0
    warning_threshold = int(config.get("warning_threshold", DEFAULT_ALERT_CONFIG["warning_threshold"]))
    critical_threshold = int(config.get("critical_threshold", DEFAULT_ALERT_CONFIG["critical_threshold"]))
    failure_rate_threshold = float(
        config.get("failure_rate_threshold", DEFAULT_ALERT_CONFIG["failure_rate_threshold"])
    )
    if args.failure_threshold is not None:
        failure_rate_threshold = float(args.failure_threshold)
    return AlertConfig(
        slo_p95_ms=slo_ms,
        warning_threshold=warning_threshold,
        critical_threshold=critical_threshold,
        failure_rate_threshold=failure_rate_threshold,
    )


def _validate_manifest_entry(entry: Mapping[str, Any]) -> None:
    try:
        schema = load_json_schema(ARCHIVE_SCHEMA_PATH)
        validate_json_schema(dict(entry), schema)
    except (FileNotFoundError, SchemaValidationError) as exc:
        raise AutomationLogError(f"invalid archive manifest entry: {exc}") from exc


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "y"}


def _write_dry_run_alerts(directory: Path, job_id: str, alerts: Sequence[AlertPayload]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "job_id": job_id,
        "alerts": [alert.as_json() for alert in alerts],
    }
    path = directory / f"{job_id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_heartbeat(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp_path, path)


def _compute_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(65536)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _parse_ts(text: str) -> datetime:
    text = (text or "").strip()
    if not text:
        raise ValueError("timestamp cannot be empty")
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _format_ts(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())
