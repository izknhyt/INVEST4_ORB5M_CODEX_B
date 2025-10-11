"""Lightweight JSON schema validation utilities used by automation tooling."""

from __future__ import annotations

import json
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

__all__ = ["SchemaValidationError", "load_json_schema", "validate_json_schema"]


class SchemaValidationError(ValueError):
    """Raised when a JSON payload violates the provided schema."""


@lru_cache(maxsize=32)
def load_json_schema(path: Path | str) -> Mapping[str, Any]:
    schema_path = Path(path)
    if not schema_path.exists():
        raise FileNotFoundError(f"Schema file not found: {schema_path}")
    with schema_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def validate_json_schema(payload: Mapping[str, Any], schema: Mapping[str, Any]) -> None:
    """Validate *payload* against *schema* using a minimal JSON Schema subset."""

    if schema.get("type") != "object":
        raise SchemaValidationError("root schema must describe an object")
    _validate_object(payload, schema)


def _validate_object(payload: Mapping[str, Any], schema: Mapping[str, Any]) -> None:
    required = schema.get("required", [])
    for key in required:
        if key not in payload:
            raise SchemaValidationError(f"Missing required field: {key}")

    properties = schema.get("properties", {})
    additional = schema.get("additionalProperties", True)
    for key, value in payload.items():
        if key in properties:
            _validate_property(value, properties[key], key)
        elif isinstance(additional, Mapping):
            _validate_property(value, additional, key)
        elif not additional:
            raise SchemaValidationError(f"Unexpected property: {key}")


def _validate_property(value: Any, schema: Mapping[str, Any], key: str) -> None:
    schema_type = schema.get("type")
    if schema_type == "object":
        if not isinstance(value, Mapping):
            raise SchemaValidationError(f"Field '{key}' must be an object")
        _validate_object(value, schema)
        return
    if schema_type == "array":
        if not isinstance(value, list):
            raise SchemaValidationError(f"Field '{key}' must be an array")
        items_schema = schema.get("items")
        if items_schema:
            for index, element in enumerate(value):
                _validate_property(element, items_schema, f"{key}[{index}]")
        return
    if schema_type == "integer":
        if not isinstance(value, int):
            raise SchemaValidationError(f"Field '{key}' must be an integer")
    elif schema_type == "number":
        if not isinstance(value, (int, float)):
            raise SchemaValidationError(f"Field '{key}' must be a number")
    elif schema_type == "boolean":
        if not isinstance(value, bool):
            raise SchemaValidationError(f"Field '{key}' must be a boolean")
    elif schema_type == "string":
        if not isinstance(value, str):
            raise SchemaValidationError(f"Field '{key}' must be a string")
    elif schema_type is not None:
        raise SchemaValidationError(f"Unsupported schema type '{schema_type}' for field '{key}'")

    if "enum" in schema and value not in schema["enum"]:
        raise SchemaValidationError(f"Field '{key}' must be one of {schema['enum']}")
    if isinstance(value, (int, float)):
        minimum = schema.get("minimum")
        if minimum is not None and value < minimum:
            raise SchemaValidationError(f"Field '{key}' must be >= {minimum}")
        maximum = schema.get("maximum")
        if maximum is not None and value > maximum:
            raise SchemaValidationError(f"Field '{key}' must be <= {maximum}")

    if schema.get("type") == "string":
        pattern = schema.get("pattern")
        if pattern and not re.match(pattern, value):
            raise SchemaValidationError(f"Field '{key}' does not match pattern {pattern}")
        if schema.get("format") == "date-time":
            _validate_datetime(value, key)


def _validate_datetime(value: str, key: str) -> None:
    candidate = value
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise SchemaValidationError(f"Field '{key}' must be ISO8601 date-time") from exc
