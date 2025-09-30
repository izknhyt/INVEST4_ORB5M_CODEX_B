"""Credential loading helpers for ingestion scripts."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Iterable

from core.utils import yaml_compat as yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_KEYS_PATH = ROOT / "configs/api_keys.yml"
LOCAL_OVERRIDE = ROOT / "configs/api_keys.local.yml"


def _normalize_service(service: str) -> str:
    return service.strip().lower().replace(" ", "_")


def load_api_credentials(
    service: str,
    *,
    required: Iterable[str] | None = None,
    path: Path | None = None,
) -> Dict[str, str]:
    """Load API credentials for ``service`` from YAML and environment variables."""

    normalized = _normalize_service(service)
    keys_path = Path(path) if path is not None else DEFAULT_KEYS_PATH

    merged: Dict[str, str] = {}
    for candidate in (keys_path, LOCAL_OVERRIDE):
        if not candidate.exists():
            continue
        try:
            with candidate.open(encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
        except Exception as exc:  # pragma: no cover - unlikely I/O failure
            raise RuntimeError(f"failed_to_load_credentials:{candidate}") from exc
        if not isinstance(data, dict):
            continue
        block = data.get(normalized)
        if isinstance(block, dict):
            merged.update({k: str(v) for k, v in block.items() if v is not None})

    env_prefix = normalized.upper().replace("-", "_")
    for env_key, env_value in os.environ.items():
        if not env_key.startswith(env_prefix + "_"):
            continue
        key = env_key[len(env_prefix) + 1 :].lower()
        merged[key] = env_value

    if required:
        missing = [name for name in required if not merged.get(name)]
        if missing:
            raise RuntimeError(
                "missing_api_credentials:"
                f"{normalized}:{','.join(sorted(missing))}"
            )

    return merged


__all__ = ["load_api_credentials"]
