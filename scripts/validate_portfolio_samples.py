"""Validate router demo portfolio sample artefacts.

This helper ensures the curated metrics under
``reports/portfolio_samples/router_demo/`` continue to mirror the strategy
manifests they were derived from. It checks that:

* Each metrics file declares a manifest id that resolves to a real manifest
  on disk, and that the manifest id matches the YAML's ``meta.id``.
* The embedded manifest copy in ``metrics/configs/`` matches the source
  configuration so reviewers can diff artefact changes confidently.
* Equity curves remain parseable by :mod:`scripts.build_router_snapshot`
  helpers (guarding against format regressions).
* ``telemetry.json`` references only manifest ids that have corresponding
  metrics payloads.

The CLI exits non-zero when a validation error is encountered.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_SAMPLES_DIR = ROOT / "reports" / "portfolio_samples" / "router_demo"

from configs.strategies.loader import iter_manifest_paths, load_manifest
from scripts.build_router_snapshot import _normalise_curve


@dataclass(frozen=True)
class ValidationResult:
    """Summary of validated artefacts."""

    samples_dir: Path
    telemetry_path: Path
    metrics_paths: Mapping[str, Path]


class SampleValidationError(ValueError):
    """Raised when curated sample validation fails."""


def _collect_allowed_manifests(inputs: Sequence[Path]) -> Dict[str, Path]:
    manifest_paths: Dict[str, Path] = {}
    for raw_path in inputs:
        for path in iter_manifest_paths([raw_path]):
            manifest = load_manifest(path)
            key = manifest.id
            resolved = path.resolve()
            if key in manifest_paths and manifest_paths[key] != resolved:
                raise SampleValidationError(
                    f"duplicate manifest id '{key}' discovered at {resolved} and {manifest_paths[key]}"
                )
            manifest_paths[key] = resolved
    return manifest_paths


def _resolve_repo_path(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def _load_json(path: Path) -> Mapping[str, object]:
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive guard
        raise SampleValidationError(f"failed to parse JSON from {path}: {exc}") from exc


def _validate_metrics_file(
    path: Path,
    *,
    allowed_manifests: Mapping[str, Path],
    embedded_root: Path,
) -> tuple[str, Path]:
    payload = _load_json(path)
    manifest_id = payload.get("manifest_id")
    if not isinstance(manifest_id, str) or not manifest_id.strip():
        raise SampleValidationError(f"metrics file {path} missing manifest_id")
    manifest_id = manifest_id.strip()

    declared_path_raw = payload.get("manifest_path")
    if not isinstance(declared_path_raw, str) or not declared_path_raw.strip():
        raise SampleValidationError(
            f"metrics file {path} missing manifest_path for manifest {manifest_id}"
        )
    declared_path = declared_path_raw.strip()

    resolved_manifest_path = _resolve_repo_path(declared_path)
    if not resolved_manifest_path.exists():
        raise SampleValidationError(
            f"manifest path {declared_path} declared by {manifest_id} does not exist on disk"
        )
    manifest = load_manifest(resolved_manifest_path)
    if manifest.id != manifest_id:
        raise SampleValidationError(
            f"manifest id mismatch for {manifest_id}: YAML at {resolved_manifest_path} reports id {manifest.id}"
        )

    if allowed_manifests:
        allowed_path = allowed_manifests.get(manifest_id)
        if allowed_path is None:
            raise SampleValidationError(
                f"manifest {manifest_id} not present in allowed manifest list ({sorted(allowed_manifests)})"
            )
        if allowed_path != resolved_manifest_path.resolve():
            raise SampleValidationError(
                "manifest path mismatch for {id}: expected {expected}, found {actual}".format(
                    id=manifest_id,
                    expected=allowed_path,
                    actual=resolved_manifest_path,
                )
            )

    embedded_manifest_path = embedded_root / declared_path
    if not embedded_manifest_path.exists():
        raise SampleValidationError(
            f"embedded manifest copy missing for {manifest_id}: expected {embedded_manifest_path}"
        )
    source_text = resolved_manifest_path.read_text(encoding="utf-8")
    embedded_text = embedded_manifest_path.read_text(encoding="utf-8")
    if source_text != embedded_text:
        raise SampleValidationError(
            f"embedded manifest for {manifest_id} differs from source {resolved_manifest_path}"
        )

    curve = payload.get("equity_curve")
    _normalise_curve(curve, manifest_id=manifest_id, source=path)

    return manifest_id, path


def validate_samples(
    samples_dir: Path,
    *,
    allowed_manifests: Sequence[Path] | None = None,
) -> ValidationResult:
    samples_dir = samples_dir.resolve()
    metrics_dir = samples_dir / "metrics"
    telemetry_path = samples_dir / "telemetry.json"

    if not metrics_dir.exists():
        raise SampleValidationError(f"metrics directory missing: {metrics_dir}")
    if not telemetry_path.exists():
        raise SampleValidationError(f"telemetry.json missing at {telemetry_path}")

    allowed_map: Dict[str, Path] = {}
    if allowed_manifests:
        allowed_map = _collect_allowed_manifests([Path(p) for p in allowed_manifests])

    metrics_paths: Dict[str, Path] = {}
    embedded_root = metrics_dir

    for candidate in sorted(metrics_dir.glob("*.json")):
        if not candidate.is_file():
            continue
        manifest_id, metric_path = _validate_metrics_file(
            candidate,
            allowed_manifests=allowed_map,
            embedded_root=embedded_root,
        )
        if manifest_id in metrics_paths:
            raise SampleValidationError(
                f"duplicate metrics file discovered for manifest {manifest_id}: {metrics_paths[manifest_id]} and {metric_path}"
            )
        metrics_paths[manifest_id] = metric_path

    telemetry_payload = _load_json(telemetry_path)
    active_positions = telemetry_payload.get("active_positions")
    if isinstance(active_positions, Mapping):
        unknown_ids = sorted(set(active_positions) - set(metrics_paths))
        if unknown_ids:
            raise SampleValidationError(
                f"telemetry.json references unknown manifest ids: {', '.join(unknown_ids)}"
            )

    if not metrics_paths:
        raise SampleValidationError(f"no metrics files discovered under {metrics_dir}")

    return ValidationResult(
        samples_dir=samples_dir,
        telemetry_path=telemetry_path,
        metrics_paths=metrics_paths,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--samples-dir",
        type=Path,
        default=DEFAULT_SAMPLES_DIR,
        help="Portfolio sample directory to validate (default: reports/portfolio_samples/router_demo)",
    )
    parser.add_argument(
        "--manifest",
        action="append",
        default=[],
        type=Path,
        help="Strategy manifest file or directory that must contain all referenced manifest ids.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        result = validate_samples(args.samples_dir, allowed_manifests=args.manifest or None)
    except SampleValidationError as exc:
        print("Portfolio sample validation failed:")
        print(f"  - {exc}")
        return 1

    manifest_list = ", ".join(sorted(result.metrics_paths))
    print(
        "Validated telemetry ({telemetry}) and metrics for manifests: {manifests}".format(
            telemetry=result.telemetry_path,
            manifests=manifest_list,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
