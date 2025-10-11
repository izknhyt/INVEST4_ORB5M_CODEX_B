"""Utilities for writing observability automation logs."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

import fcntl


__all__ = [
    "AutomationLogError",
    "AutomationLogSchemaError",
    "generate_job_id",
    "log_automation_event",
    "log_automation_event_with_sequence",
]


AUTOMATION_LOG_PATH = Path("ops/automation_runs.log")
AUTOMATION_SEQUENCE_PATH = Path("ops/automation_runs.sequence")
AUTOMATION_SCHEMA_PATH = Path("schemas/automation_run.schema.json")
_MAX_LOG_BYTES = 4096
_ALLOWED_STATUS = {"ok", "error", "skipped", "dry_run", "warning"}
_JOB_ID_PATTERN = re.compile(r"^[0-9TZ:-]+-[a-z0-9_-]+$")


from ._schema import SchemaValidationError, load_json_schema, validate_json_schema


class AutomationLogError(RuntimeError):
    """Raised when an automation log entry cannot be persisted."""


class AutomationLogSchemaError(AutomationLogError):
    """Raised when an automation log entry violates the schema."""


def generate_job_id(job_name: str, *, when: Optional[datetime] = None) -> str:
    """Return a job identifier following ``YYYYMMDDThhmmssZ-<job>``.

    Parameters
    ----------
    job_name:
        Descriptive name of the job. ``job_name`` is normalised to
        lowercase, whitespace is collapsed to single hyphens, and characters
        outside ``[a-z0-9_-]`` are stripped.
    when:
        Optional timestamp; defaults to ``datetime.now(timezone.utc)``.
    """

    if not job_name:
        raise ValueError("job_name must be a non-empty string")

    timestamp = (when or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    slug = re.sub(r"[^a-z0-9_-]+", "", job_name.lower().replace(" ", "-"))
    if not slug:
        raise ValueError("job_name must contain at least one alphanumeric character")
    return f"{timestamp}-{slug}"


def log_automation_event(
    job_id: str,
    status: str,
    *,
    log_path: Path | str = AUTOMATION_LOG_PATH,
    schema_path: Path | str = AUTOMATION_SCHEMA_PATH,
    sequence: Optional[int] = None,
    duration_ms: Optional[int] = None,
    attempts: Optional[int] = None,
    artefacts: Optional[Iterable[str]] = None,
    alerts: Optional[Iterable[Mapping[str, Any]]] = None,
    diagnostics: Optional[Mapping[str, Any]] = None,
    message: Optional[str] = None,
    extra: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Append a structured automation log entry.

    The entry is validated against ``schemas/automation_run.schema.json`` and
    written as a single JSON line. A ``ValueError`` is raised when the payload
    exceeds ``4096`` bytes, matching the size guard described in the design.
    """

    if status not in _ALLOWED_STATUS:
        raise AutomationLogSchemaError(f"Unsupported status '{status}'")
    if not _JOB_ID_PATTERN.match(job_id):
        raise AutomationLogSchemaError(f"job_id '{job_id}' does not match required pattern")

    entry: Dict[str, Any] = {
        "job_id": job_id,
        "status": status,
        "logged_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    if sequence is not None:
        entry["sequence"] = sequence
    if duration_ms is not None:
        entry["duration_ms"] = int(duration_ms)
    if attempts is not None:
        entry["attempts"] = int(attempts)
    if artefacts is not None:
        entry["artefacts"] = list(artefacts)
    if alerts is not None:
        entry["alerts"] = [dict(alert) for alert in alerts]
    if diagnostics is not None:
        entry["diagnostics"] = dict(diagnostics)
    if message is not None:
        entry["message"] = message
    if extra:
        for key, value in extra.items():
            if key not in entry:
                entry[key] = value

    schema = load_json_schema(Path(schema_path))
    try:
        validate_json_schema(entry, schema)
    except SchemaValidationError as exc:
        raise AutomationLogSchemaError(str(exc)) from exc
    _write_jsonl(entry, Path(log_path))
    return entry


def log_automation_event_with_sequence(
    job_id: str,
    status: str,
    *,
    log_path: Path | str = AUTOMATION_LOG_PATH,
    schema_path: Path | str = AUTOMATION_SCHEMA_PATH,
    sequence_path: Path | str = AUTOMATION_SEQUENCE_PATH,
    duration_ms: Optional[int] = None,
    attempts: Optional[int] = None,
    artefacts: Optional[Iterable[str]] = None,
    alerts: Optional[Iterable[Mapping[str, Any]]] = None,
    diagnostics: Optional[Mapping[str, Any]] = None,
    message: Optional[str] = None,
    extra: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Log an automation event while maintaining a monotonically increasing sequence."""

    log_path = Path(log_path)
    sequence_path = Path(sequence_path)
    _ensure_parent(log_path)
    _ensure_parent(sequence_path)

    with _locked_sequence_handle(sequence_path) as seq_handle:
        next_sequence = _read_next_sequence(seq_handle)
        gap_warning = _prepare_sequence_gap_warning(
            job_id,
            log_path,
            sequence_path,
            expected_previous_sequence=next_sequence - 1,
            next_sequence=next_sequence,
        )
        if gap_warning is not None:
            log_automation_event(
                gap_warning["job_id"],
                "warning",
                log_path=log_path,
                schema_path=schema_path,
                diagnostics=gap_warning["diagnostics"],
                message=gap_warning["message"],
            )
        entry = log_automation_event(
            job_id,
            status,
            log_path=log_path,
            schema_path=schema_path,
            sequence=next_sequence,
            duration_ms=duration_ms,
            attempts=attempts,
            artefacts=artefacts,
            alerts=alerts,
            diagnostics=diagnostics,
            message=message,
            extra=extra,
        )
        _write_sequence(seq_handle, next_sequence)
        return entry


def _prepare_sequence_gap_warning(
    job_id: str,
    log_path: Path,
    sequence_path: Path,
    *,
    expected_previous_sequence: int,
    next_sequence: int,
) -> Optional[Dict[str, Any]]:
    if expected_previous_sequence < 1:
        return None
    last_entry = _read_last_log_entry(log_path)
    if not last_entry:
        return None
    last_sequence = last_entry.get("sequence")
    if not isinstance(last_sequence, int):
        return None
    if last_sequence == expected_previous_sequence:
        return None

    diagnostics: Dict[str, Any] = {
        "error_code": "sequence_gap",
        "expected_previous_sequence": expected_previous_sequence,
        "observed_previous_sequence": last_sequence,
        "next_sequence": next_sequence,
        "gap_size": abs(expected_previous_sequence - last_sequence),
        "gap_direction": (
            "observed_lower"
            if last_sequence < expected_previous_sequence
            else "observed_higher"
        ),
        "detected_for_job_id": job_id,
        "sequence_path": str(sequence_path),
        "log_path": str(log_path),
    }
    if isinstance(last_entry.get("job_id"), str):
        diagnostics["observed_previous_job_id"] = last_entry["job_id"]
    if isinstance(last_entry.get("logged_at"), str):
        diagnostics["observed_previous_logged_at"] = last_entry["logged_at"]

    message = (
        "Detected automation run sequence gap: "
        f"expected previous sequence {expected_previous_sequence}, "
        f"observed {last_sequence}."
    )
    return {
        "job_id": _derive_sequence_gap_job_id(job_id),
        "message": message,
        "diagnostics": diagnostics,
    }


def _read_last_log_entry(path: Path) -> Optional[Mapping[str, Any]]:
    if not path.exists():
        return None
    with path.open("rb") as handle:
        handle.seek(0, 2)
        file_size = handle.tell()
        if file_size == 0:
            return None
        chunk_size = 4096
        data = b""
        cursor = file_size
        while cursor > 0:
            read_size = min(chunk_size, cursor)
            cursor -= read_size
            handle.seek(cursor)
            data = handle.read(read_size) + data
            lines = data.splitlines()
            for raw_line in reversed(lines):
                stripped = raw_line.strip()
                if not stripped:
                    continue
                try:
                    decoded = stripped.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise AutomationLogError(
                        f"Failed to decode last log entry in {path}: {exc}"
                    ) from exc
                try:
                    return json.loads(decoded)
                except json.JSONDecodeError as exc:
                    raise AutomationLogError(
                        f"Failed to parse last log entry in {path}: {exc}"
                    ) from exc
        return None


def _derive_sequence_gap_job_id(job_id: str) -> str:
    if _JOB_ID_PATTERN.match(job_id):
        timestamp, _, _ = job_id.partition("-")
        if timestamp:
            return f"{timestamp}-sequence-gap"
    return f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-sequence-gap"


def _write_jsonl(entry: Mapping[str, Any], path: Path) -> None:
    _ensure_parent(path)
    line = json.dumps(entry, separators=(",", ":"))
    byte_length = len(line.encode("utf-8"))
    if byte_length > _MAX_LOG_BYTES:
        raise AutomationLogError(
            f"Log entry exceeds {_MAX_LOG_BYTES} bytes ({byte_length} bytes computed)"
        )
    with path.open("a", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            handle.write(line + "\n")
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


@dataclass
class _SequenceHandle:
    path: Path
    handle: Any

    def __enter__(self) -> "_SequenceHandle":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        self.handle.close()


def _locked_sequence_handle(path: Path) -> _SequenceHandle:
    handle = path.open("a+", encoding="utf-8")
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    return _SequenceHandle(path=path, handle=handle)


def _read_next_sequence(sequence_handle: _SequenceHandle) -> int:
    sequence_handle.handle.seek(0)
    data_text = sequence_handle.handle.read().strip()
    if not data_text:
        return 1
    try:
        data = json.loads(data_text)
    except json.JSONDecodeError as exc:
        raise AutomationLogError(f"Failed to parse {sequence_handle.path}: {exc}") from exc
    value = data.get("value")
    if not isinstance(value, int) or value < 0:
        raise AutomationLogError("sequence file must contain a non-negative integer 'value'")
    return value + 1


def _write_sequence(sequence_handle: _SequenceHandle, value: int) -> None:
    sequence_handle.handle.seek(0)
    sequence_handle.handle.truncate(0)
    payload = {"value": value, "updated_at": datetime.now(timezone.utc).isoformat()}
    json.dump(payload, sequence_handle.handle, separators=(",", ":"))
    sequence_handle.handle.write("\n")
    sequence_handle.handle.flush()


