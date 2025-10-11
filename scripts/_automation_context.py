"""Shared automation context helpers for observability jobs."""

from __future__ import annotations

import os
import shlex
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence

from ._automation_logging import generate_job_id

__all__ = ["AutomationContext", "build_automation_context"]


@dataclass(frozen=True)
class AutomationContext:
    """Captured environment for an automation job run."""

    job_name: str
    job_id: str
    started_at: datetime
    command: str
    commit_sha: Optional[str] = None
    config_path: Optional[Path] = None
    environment: Mapping[str, str] = field(default_factory=dict, repr=False)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def get_secret(self, env_key: str) -> Optional[str]:
        """Return the raw value of ``env_key`` if present in the environment."""

        return self.environment.get(env_key)

    def describe(self, *, redact: Optional[Iterable[str]] = None) -> Dict[str, Any]:
        """Return a redacted snapshot suitable for structured logs."""

        redacted_keys = set(redact or [])
        env_snapshot: Dict[str, str] = {}
        for key, value in self.environment.items():
            if key in redacted_keys or _should_auto_redact(key):
                env_snapshot[key] = "<redacted>"
            else:
                env_snapshot[key] = value
        return {
            "job_name": self.job_name,
            "job_id": self.job_id,
            "started_at": self.started_at.isoformat().replace("+00:00", "Z"),
            "command": self.command,
            "commit_sha": self.commit_sha,
            "config_path": str(self.config_path) if self.config_path else None,
            "metadata": dict(self.metadata),
            "environment": env_snapshot,
        }

    def as_log_payload(self, *, include_environment: bool = False) -> Dict[str, Any]:
        """Generate a serialisable payload for automation logs."""

        payload = {
            "job_name": self.job_name,
            "job_id": self.job_id,
            "started_at": self.started_at.isoformat().replace("+00:00", "Z"),
            "command": self.command,
            "commit_sha": self.commit_sha,
            "config_path": str(self.config_path) if self.config_path else None,
            "metadata": dict(self.metadata),
        }
        if include_environment:
            payload["environment"] = self.describe()["environment"]
        return payload


def build_automation_context(
    job_name: str,
    *,
    job_id: Optional[str] = None,
    when: Optional[datetime] = None,
    config_path: Optional[Path | str] = None,
    env: Optional[Mapping[str, str]] = None,
    argv: Optional[Sequence[str]] = None,
    metadata: Optional[Mapping[str, Any]] = None,
) -> AutomationContext:
    """Construct an :class:`AutomationContext` using repository conventions."""

    env_map = dict(env or os.environ)
    started_at = _normalise_timestamp(when)
    resolved_job_id = job_id or generate_job_id(job_name, when=started_at)
    resolved_config = Path(config_path) if config_path else None
    metadata_map = dict(metadata or {})
    return AutomationContext(
        job_name=job_name,
        job_id=resolved_job_id,
        started_at=started_at,
        command=_resolve_command(argv),
        commit_sha=_resolve_commit_sha(env_map),
        config_path=resolved_config,
        environment=env_map,
        metadata=metadata_map,
    )


def _resolve_command(argv: Optional[Sequence[str]]) -> str:
    args = list(argv) if argv is not None else sys.argv
    if not args:
        return ""
    return shlex.join(args)


def _resolve_commit_sha(env_map: Mapping[str, str]) -> Optional[str]:
    for key in (
        "OBS_COMMIT_SHA",
        "GIT_COMMIT_SHA",
        "CI_COMMIT_SHA",
        "GITHUB_SHA",
        "COMMIT_SHA",
        "GIT_COMMIT",
    ):
        value = env_map.get(key)
        if value:
            return value
    return None


def _should_auto_redact(env_key: str) -> bool:
    upper_key = env_key.upper()
    sensitive_tokens = ("SECRET", "TOKEN", "KEY", "PASSWORD", "CREDENTIAL", "PRIVATE")
    return any(token in upper_key for token in sensitive_tokens)


def _normalise_timestamp(value: Optional[datetime]) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
