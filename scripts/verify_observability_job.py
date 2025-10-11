"""Utilities for verifying observability automation artefacts.

This module implements the CLI described in
``docs/phase3_detailed_design.md``.  It inspects automation logs,
heartbeat files, dashboard manifests, and required secrets so that a
single command can validate whether the observability automation suite
is healthy.  Results are emitted as JSON and also captured in
``ops/automation_runs.log`` via :func:`log_automation_event_with_sequence`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence

from scripts._automation_context import build_automation_context
from scripts._automation_logging import (
    AUTOMATION_LOG_PATH,
    AUTOMATION_SEQUENCE_PATH,
    AUTOMATION_SCHEMA_PATH,
    generate_job_id,
    log_automation_event_with_sequence,
)
from scripts._schema import SchemaValidationError, load_json_schema, validate_json_schema


DEFAULT_JOB_NAME = "observability-verification"
DEFAULT_SECRET_KEYS = ("OBS_WEEKLY_WEBHOOK_URL", "OBS_WEBHOOK_SECRET")
DEFAULT_HEARTBEAT_MAX_AGE_HOURS = 6.0


@dataclass(slots=True)
class CheckResult:
    """Represents the outcome of a verification check."""

    name: str
    status: str
    details: MutableMapping[str, Any]
    message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"name": self.name, "status": self.status, "details": _serialise(self.details)}
        if self.message:
            payload["message"] = self.message
        return payload


class VerificationError(RuntimeError):
    """Raised when a verification step fails."""

    def __init__(self, code: str, message: str, *, details: Optional[Mapping[str, Any]] = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})


def _parse_args(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify observability automation artefacts.")
    parser.add_argument("--job-name", default=DEFAULT_JOB_NAME, help="Name used for AutomationContext/Job ID generation.")
    parser.add_argument("--job-id", help="Job identifier. Defaults to an auto-generated value based on --job-name.")
    parser.add_argument(
        "--check-log",
        type=Path,
        default=AUTOMATION_LOG_PATH,
        help="Path to ops/automation_runs.log (JSONL).",
    )
    parser.add_argument(
        "--skip-log-check",
        action="store_true",
        help="Skip validating the automation log even if --check-log is provided.",
    )
    parser.add_argument(
        "--sequence-file",
        type=Path,
        default=AUTOMATION_SEQUENCE_PATH,
        help="Path to ops/automation_runs.sequence (JSON).",
    )
    parser.add_argument(
        "--heartbeat",
        action="append",
        type=Path,
        default=[],
        help="Heartbeat JSON file to validate. Can be specified multiple times.",
    )
    parser.add_argument(
        "--heartbeat-max-age-hours",
        type=float,
        default=DEFAULT_HEARTBEAT_MAX_AGE_HOURS,
        help="Maximum allowed age (in hours) for heartbeat last_success_at/generated_at timestamps.",
    )
    parser.add_argument(
        "--dashboard-manifest",
        type=Path,
        help="Path to out/dashboard/manifest.json to validate against dashboard schema.",
    )
    parser.add_argument(
        "--expected-dataset",
        action="append",
        default=[],
        help="Dataset name expected in the dashboard manifest (e.g. ev_history).",
    )
    parser.add_argument(
        "--check-secrets",
        action="store_true",
        help="Verify required observability secrets are present in the environment.",
    )
    parser.add_argument(
        "--secret",
        action="append",
        default=[],
        help="Environment variable that must be populated when --check-secrets is used.",
    )
    parser.add_argument(
        "--require-job-entry",
        action="store_true",
        help="Ensure --check-log contains an entry for the generated job_id (before this verification run).",
    )
    parser.add_argument(
        "--require-check",
        action="store_true",
        help="Fail if no verification checks were requested (default: inferred).",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)
    start_time = time.perf_counter()

    job_id = args.job_id or generate_job_id(args.job_name)
    context = build_automation_context(
        args.job_name,
        job_id=job_id,
        argv=["python3", "scripts/verify_observability_job.py", *(_coerce_argv(argv) if argv is not None else sys.argv[1:])],
    )

    checks: List[CheckResult] = []
    artefacts: List[str] = []
    failures: List[Dict[str, Any]] = []

    def _record_failure(result: CheckResult, error: VerificationError) -> None:
        result.status = "error"
        result.message = error.message
        result.details.update(error.details)
        failures.append({"code": error.code, "message": error.message, "details": _serialise(error.details)})

    log_checked = False

    if args.check_log and not args.skip_log_check:
        log_checked = True
        log_result = CheckResult("automation_log", "ok", {"path": str(args.check_log)})
        try:
            log_details = _verify_automation_log(args.check_log, require_job_id=job_id if args.require_job_entry else None)
            log_result.details.update(log_details)
            artefacts.append(str(args.check_log))
        except VerificationError as exc:  # pragma: no cover - exercised in targeted tests
            _record_failure(log_result, exc)
        checks.append(log_result)

        if args.sequence_file:
            sequence_result = CheckResult("automation_sequence", "ok", {"path": str(args.sequence_file)})
            try:
                expected = log_result.details.get("last_sequence")
                seq_details = _verify_sequence_file(args.sequence_file, expected_sequence=expected)
                sequence_result.details.update(seq_details)
                artefacts.append(str(args.sequence_file))
            except VerificationError as exc:
                _record_failure(sequence_result, exc)
            checks.append(sequence_result)

    for heartbeat_path in args.heartbeat:
        heartbeat_result = CheckResult("heartbeat", "ok", {"path": str(heartbeat_path)})
        try:
            hb_details = _verify_heartbeat(heartbeat_path, max_age_hours=args.heartbeat_max_age_hours)
            heartbeat_result.details.update(hb_details)
            artefacts.append(str(heartbeat_path))
        except VerificationError as exc:
            _record_failure(heartbeat_result, exc)
        checks.append(heartbeat_result)

    if args.dashboard_manifest:
        manifest_result = CheckResult("dashboard_manifest", "ok", {"path": str(args.dashboard_manifest)})
        try:
            manifest_details = _verify_dashboard_manifest(
                args.dashboard_manifest, expected_datasets=args.expected_dataset
            )
            manifest_result.details.update(manifest_details)
            artefacts.append(str(args.dashboard_manifest))
        except VerificationError as exc:
            _record_failure(manifest_result, exc)
        checks.append(manifest_result)

    if args.check_secrets:
        secret_keys = list(args.secret or DEFAULT_SECRET_KEYS)
        secrets_result = CheckResult("secrets", "ok", {"required": secret_keys})
        try:
            secret_details = _verify_secrets(secret_keys, os.environ)
            secrets_result.details.update(secret_details)
        except VerificationError as exc:
            _record_failure(secrets_result, exc)
        checks.append(secrets_result)

    if not checks and (args.require_check or log_checked or args.check_secrets):
        # No checks executed even though the caller expected them.
        result = CheckResult("configuration", "error", {}, "No verification checks were executed.")
        failures.append({"code": "no_checks", "message": result.message, "details": {}})
        checks.append(result)

    status = "ok" if not failures else "error"
    duration_ms = int((time.perf_counter() - start_time) * 1000)

    summary = {
        "job_name": args.job_name,
        "job_id": job_id,
        "status": status,
        "checks": [result.to_dict() for result in checks],
        "failures": failures,
        "duration_ms": duration_ms,
    }

    print(json.dumps(summary, ensure_ascii=False))

    diagnostics: Dict[str, Any] = {
        "job_name": args.job_name,
        "checks": [result.to_dict() for result in checks],
        "context": context.as_log_payload(),
    }
    if failures:
        diagnostics["error_code"] = "verification_failed"
        diagnostics["failures"] = failures

    log_automation_event_with_sequence(
        job_id,
        status,
        log_path=AUTOMATION_LOG_PATH,
        sequence_path=AUTOMATION_SEQUENCE_PATH,
        schema_path=AUTOMATION_SCHEMA_PATH,
        duration_ms=duration_ms,
        attempts=1,
        artefacts=artefacts,
        diagnostics=diagnostics,
    )

    return 0 if status == "ok" else 1


def _verify_automation_log(log_path: Path, *, require_job_id: Optional[str]) -> Dict[str, Any]:
    if not log_path.exists():
        raise VerificationError("log_missing", f"Automation log not found: {log_path}", details={"path": str(log_path)})

    schema = load_json_schema(AUTOMATION_SCHEMA_PATH)
    entries: List[Mapping[str, Any]] = []
    sequences: List[int] = []

    with log_path.open("r", encoding="utf-8") as handle:
        for line_no, raw_line in enumerate(handle, start=1):
            payload = raw_line.strip()
            if not payload:
                continue
            try:
                record = json.loads(payload)
            except json.JSONDecodeError as exc:  # pragma: no cover - defensive guard
                raise VerificationError(
                    "log_parse_error",
                    f"Failed to parse JSON on line {line_no}: {exc}",
                    details={"line": line_no, "path": str(log_path)},
                ) from exc
            try:
                validate_json_schema(record, schema)
            except SchemaValidationError as exc:
                raise VerificationError(
                    "log_schema_error",
                    f"Schema validation failed on line {line_no}: {exc}",
                    details={"line": line_no, "path": str(log_path)},
                ) from exc
            entries.append(record)
            sequence = record.get("sequence")
            if isinstance(sequence, int):
                sequences.append(sequence)

    if not entries:
        raise VerificationError("log_empty", "Automation log is empty", details={"path": str(log_path)})

    if sequences:
        for index in range(1, len(sequences)):
            previous = sequences[index - 1]
            current = sequences[index]
            if current != previous + 1:
                raise VerificationError(
                    "sequence_gap",
                    f"Sequence numbers must increase by 1 (observed {previous} -> {current}).",
                    details={"path": str(log_path), "previous": previous, "current": current},
                )

    if require_job_id is not None:
        if not any(entry.get("job_id") == require_job_id for entry in entries):
            raise VerificationError(
                "job_missing",
                f"No automation log entry found for job_id={require_job_id}.",
                details={"path": str(log_path), "job_id": require_job_id},
            )

    last_entry = entries[-1]
    last_sequence = sequences[-1] if sequences else None
    return {
        "entries": len(entries),
        "last_job_id": last_entry.get("job_id"),
        "last_status": last_entry.get("status"),
        "last_sequence": last_sequence,
        "last_logged_at": last_entry.get("logged_at"),
    }


def _verify_sequence_file(sequence_path: Path, *, expected_sequence: Optional[int]) -> Dict[str, Any]:
    if not sequence_path.exists():
        raise VerificationError(
            "sequence_missing", f"Sequence file not found: {sequence_path}", details={"path": str(sequence_path)}
        )

    raw_text = sequence_path.read_text(encoding="utf-8").strip()
    if not raw_text:
        raise VerificationError("sequence_empty", "Sequence file is empty", details={"path": str(sequence_path)})
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise VerificationError(
            "sequence_parse_error",
            f"Failed to parse sequence file: {exc}",
            details={"path": str(sequence_path)},
        ) from exc

    value = payload.get("value")
    updated_at = payload.get("updated_at")
    if not isinstance(value, int):
        raise VerificationError(
            "sequence_invalid_value",
            "Sequence file must contain an integer 'value'.",
            details={"path": str(sequence_path), "value": value},
        )
    if not isinstance(updated_at, str):
        raise VerificationError(
            "sequence_missing_timestamp",
            "Sequence file must include an 'updated_at' timestamp.",
            details={"path": str(sequence_path)},
        )

    parsed_timestamp = _parse_iso_timestamp(updated_at)
    if expected_sequence is not None and value != expected_sequence:
        raise VerificationError(
            "sequence_mismatch",
            f"Sequence file value {value} does not match log sequence {expected_sequence}.",
            details={"path": str(sequence_path), "value": value, "expected": expected_sequence},
        )

    return {
        "value": value,
        "updated_at": parsed_timestamp.isoformat().replace("+00:00", "Z"),
    }


def _verify_heartbeat(heartbeat_path: Path, *, max_age_hours: float) -> Dict[str, Any]:
    if not heartbeat_path.exists():
        raise VerificationError(
            "heartbeat_missing", f"Heartbeat file not found: {heartbeat_path}", details={"path": str(heartbeat_path)}
        )

    try:
        payload = json.loads(heartbeat_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise VerificationError(
            "heartbeat_parse_error",
            f"Failed to parse heartbeat JSON: {exc}",
            details={"path": str(heartbeat_path)},
        ) from exc

    timestamp_str = _extract_heartbeat_timestamp(payload)
    timestamp = _parse_iso_timestamp(timestamp_str)
    age_hours = (datetime.now(timezone.utc) - timestamp).total_seconds() / 3600.0

    if age_hours > max_age_hours:
        raise VerificationError(
            "heartbeat_stale",
            f"Heartbeat {heartbeat_path} is stale ({age_hours:.2f}h > {max_age_hours:.2f}h).",
            details={"path": str(heartbeat_path), "age_hours": age_hours, "max_age_hours": max_age_hours},
        )

    return {
        "timestamp": timestamp.isoformat().replace("+00:00", "Z"),
        "age_hours": age_hours,
    }


def _verify_dashboard_manifest(manifest_path: Path, *, expected_datasets: Iterable[str]) -> Dict[str, Any]:
    if not manifest_path.exists():
        raise VerificationError(
            "manifest_missing", f"Dashboard manifest not found: {manifest_path}", details={"path": str(manifest_path)}
        )

    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise VerificationError(
            "manifest_parse_error",
            f"Failed to parse dashboard manifest: {exc}",
            details={"path": str(manifest_path)},
        ) from exc

    schema = load_json_schema(Path("schemas/dashboard_manifest.schema.json"))
    try:
        validate_json_schema(payload, schema)
    except SchemaValidationError as exc:
        raise VerificationError(
            "manifest_schema_error",
            f"Dashboard manifest failed schema validation: {exc}",
            details={"path": str(manifest_path)},
        ) from exc

    datasets = [dataset.get("dataset") for dataset in payload.get("datasets", [])]
    missing = [name for name in expected_datasets if name not in datasets]
    if missing:
        raise VerificationError(
            "manifest_missing_dataset",
            f"Manifest missing expected datasets: {', '.join(missing)}",
            details={"path": str(manifest_path), "missing": missing, "present": datasets},
        )

    return {
        "sequence": payload.get("sequence"),
        "generated_at": payload.get("generated_at"),
        "datasets": datasets,
    }


def _verify_secrets(secret_keys: Iterable[str], env: Mapping[str, str]) -> Dict[str, Any]:
    missing = [key for key in secret_keys if not env.get(key)]
    if missing:
        raise VerificationError("missing_secrets", "Required secrets are missing or empty.", details={"missing": missing})
    return {"validated": sorted(secret_keys)}


def _extract_heartbeat_timestamp(payload: Mapping[str, Any]) -> str:
    for candidate in ("last_success_at", "generated_at"):
        value = payload.get(candidate)
        if isinstance(value, str) and value:
            return value
    raise VerificationError(
        "heartbeat_missing_timestamp",
        "Heartbeat payload must contain 'last_success_at' or 'generated_at'.",
        details={"available_keys": list(payload.keys())},
    )


def _parse_iso_timestamp(value: str) -> datetime:
    candidate = value.strip()
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise VerificationError("invalid_timestamp", f"Invalid ISO8601 timestamp: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        parsed = parsed.astimezone(timezone.utc)
    return parsed


def _serialise(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _serialise(val) for key, val in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_serialise(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    return value


def _coerce_argv(argv: Optional[Sequence[str]]) -> Sequence[str]:
    if argv is None:
        return sys.argv[1:]
    return list(argv)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

