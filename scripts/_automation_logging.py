"""Utilities for writing observability automation logs."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

import fcntl
from functools import lru_cache


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

    _validate_entry(entry, Path(schema_path))
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


def _validate_entry(entry: Mapping[str, Any], schema_path: Path) -> None:
    schema = _load_schema(schema_path)
    try:
        _validate_against_schema(entry, schema)
    except AutomationLogSchemaError:
        raise
    except Exception as exc:  # pragma: no cover - defensive catch
        raise AutomationLogSchemaError(str(exc)) from exc


@lru_cache(maxsize=1)
def _load_schema(schema_path: Path) -> Mapping[str, Any]:
    if not schema_path.exists():
        raise AutomationLogError(f"Schema file not found: {schema_path}")
    with schema_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _validate_against_schema(entry: Mapping[str, Any], schema: Mapping[str, Any]) -> None:
    if schema.get("type") != "object":
        raise AutomationLogSchemaError("automation log schema must describe an object")
    required = schema.get("required", [])
    for key in required:
        if key not in entry:
            raise AutomationLogSchemaError(f"Missing required field: {key}")
    properties = schema.get("properties", {})
    additional = schema.get("additionalProperties", True)
    for key, value in entry.items():
        if key in properties:
            _validate_property(value, properties[key], key)
        elif isinstance(additional, Mapping):
            _validate_property(value, additional, key)
        elif not additional:
            raise AutomationLogSchemaError(f"Unexpected property: {key}")


def _validate_property(value: Any, schema: Mapping[str, Any], key: str) -> None:
    expected_type = schema.get("type")
    if expected_type:
        _validate_type(value, expected_type, key)
    if "enum" in schema and value not in schema["enum"]:
        raise AutomationLogSchemaError(f"Field '{key}' must be one of {schema['enum']}")
    if isinstance(value, (int, float)) and "minimum" in schema:
        if value < schema["minimum"]:
            raise AutomationLogSchemaError(
                f"Field '{key}' must be >= {schema['minimum']} (received {value})"
            )
    if schema.get("type") == "string" and "pattern" in schema:
        if not re.match(schema["pattern"], value):
            raise AutomationLogSchemaError(
                f"Field '{key}' does not match pattern {schema['pattern']}"
            )
    if schema.get("type") == "string" and schema.get("format") == "date-time":
        _validate_datetime(value, key)
    if schema.get("type") == "array":
        items = schema.get("items")
        if items:
            for index, element in enumerate(value):
                _validate_property(element, items, f"{key}[{index}]")
    if schema.get("type") == "object":
        nested_properties = schema.get("properties", {})
        nested_required = schema.get("required", [])
        nested_additional = schema.get("additionalProperties", True)
        for nested_key in nested_required:
            if nested_key not in value:
                raise AutomationLogSchemaError(
                    f"Field '{key}' is missing required property '{nested_key}'"
                )
        for nested_key, nested_value in value.items():
            if nested_key in nested_properties:
                _validate_property(nested_value, nested_properties[nested_key], f"{key}.{nested_key}")
            elif isinstance(nested_additional, Mapping):
                _validate_property(nested_value, nested_additional, f"{key}.{nested_key}")
            elif not nested_additional:
                raise AutomationLogSchemaError(
                    f"Field '{key}' has unexpected property '{nested_key}'"
                )


def _validate_type(value: Any, expected: str, key: str) -> None:
    type_map = {
        "string": str,
        "integer": int,
        "number": (int, float),
        "object": Mapping,
        "array": Iterable,
        "boolean": bool,
    }
    python_type = type_map.get(expected)
    if python_type is None:
        return
    if expected == "array":
        if not isinstance(value, list):
            raise AutomationLogSchemaError(f"Field '{key}' must be an array")
    elif expected == "object":
        if not isinstance(value, Mapping):
            raise AutomationLogSchemaError(f"Field '{key}' must be an object")
    elif expected == "integer":
        if not isinstance(value, int):
            raise AutomationLogSchemaError(f"Field '{key}' must be an integer")
    elif expected == "number":
        if not isinstance(value, (int, float)):
            raise AutomationLogSchemaError(f"Field '{key}' must be a number")
    else:
        if not isinstance(value, python_type):
            raise AutomationLogSchemaError(f"Field '{key}' must be of type {expected}")


def _validate_datetime(value: str, key: str) -> None:
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        datetime.fromisoformat(value)
    except ValueError as exc:  # pragma: no cover - should be rare
        raise AutomationLogSchemaError(f"Field '{key}' must be ISO8601 date-time") from exc
