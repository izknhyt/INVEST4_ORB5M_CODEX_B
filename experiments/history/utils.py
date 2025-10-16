"""Shared helpers for experiment history scripts."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from . import REPO_ROOT


def load_json(path: Path) -> Dict[str, Any]:
    with path.open() as handle:
        return json.load(handle)


def relative_to_repo(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def extract_timestamp_iso(run_id: str) -> str:
    match = re.search(r"(20\d{2})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})$", run_id)
    if not match:
        return ""
    year, month, day, hour, minute, second = (int(group) for group in match.groups())
    dt = datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def compute_dataset_fingerprint(path: Path) -> Tuple[str, int]:
    hasher = hashlib.sha256()
    rows = 0
    with path.open("rb") as handle:
        first_line = handle.readline()
        if not first_line:
            return hasher.hexdigest(), 0
        try:
            first_line_text = first_line.decode("utf-8")
        except UnicodeDecodeError:
            hasher.update(first_line)
            rows += 1
            first_line_text = ""
        stripped = first_line_text.lstrip()
        header_consumed = bool(stripped) and stripped[0].isalpha()
        if not header_consumed:
            hasher.update(first_line)
            rows += 1
        for chunk in handle:
            hasher.update(chunk)
            rows += 1
    return hasher.hexdigest(), rows


def ensure_utf8(path: Path) -> None:
    data = path.read_bytes()
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as exc:  # pragma: no cover - defensive guard
        raise ValueError(f"File {path} is not UTF-8 encoded") from exc


def safe_get(data: Dict[str, Any], key: str, default: Optional[Any] = None) -> Optional[Any]:
    value = data.get(key, default)
    return value


__all__ = [
    "load_json",
    "relative_to_repo",
    "extract_timestamp_iso",
    "compute_dataset_fingerprint",
    "ensure_utf8",
    "safe_get",
]
