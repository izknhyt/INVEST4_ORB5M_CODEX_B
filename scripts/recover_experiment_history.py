#!/usr/bin/env python3
"""Utilities to rebuild experiment history artefacts."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from experiments.history import (
    PARQUET_COLUMNS,
    PARQUET_PATH,
    RUNS_DIR,
    ensure_layout,
    read_parquet,
    rows_to_table,
    write_parquet,
)
from experiments.history.utils import load_json


class ExperimentRecoveryError(RuntimeError):
    """Raised when recovery cannot proceed."""


def _parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-json", action="store_true", help="Rebuild Parquet from per-run JSON entries")
    parser.add_argument("--json-dir", default=str(RUNS_DIR), help="Directory containing per-run JSON entries")
    parser.add_argument("--parquet", default=str(PARQUET_PATH), help="Destination Parquet file")
    parser.add_argument("--dry-run", action="store_true", help="Preview actions without writing")
    return parser.parse_args(argv)


def _rows_from_json(json_paths: List[Path]) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    seen: set[str] = set()
    for path in sorted(json_paths):
        payload = load_json(path)
        run_id = payload.get("run_id")
        if not run_id:
            raise ExperimentRecoveryError(f"Run id missing in {path}")
        if run_id in seen:
            raise ExperimentRecoveryError(f"Duplicate run id detected: {run_id}")
        seen.add(run_id)
        row = {column: payload.get(column) for column in PARQUET_COLUMNS}
        rows.append(row)
    return rows


def _rebuild_from_json(parquet_path: Path, json_dir: Path, dry_run: bool) -> int:
    if not json_dir.exists():
        raise ExperimentRecoveryError(f"JSON directory not found: {json_dir}")
    json_paths = [path for path in json_dir.iterdir() if path.suffix == ".json" and path.is_file()]
    if not json_paths:
        raise ExperimentRecoveryError(f"No JSON entries found under {json_dir}")
    rows = _rows_from_json(json_paths)
    table = rows_to_table(rows)
    if dry_run:
        print(json.dumps({"rows": len(rows)}, indent=2))
        return len(rows)
    write_parquet(table, parquet_path)
    reloaded = read_parquet(parquet_path)
    if reloaded is None:
        raise ExperimentRecoveryError(f"Failed to read back parquet {parquet_path}")
    if reloaded.num_rows != len(rows):
        raise ExperimentRecoveryError(
            f"Row count mismatch: expected {len(rows)}, observed {reloaded.num_rows}"
        )
    return len(rows)


def recover_history(argv: Optional[Iterable[str]] = None) -> int:
    args = _parse_args(argv)
    if not args.from_json:
        raise ExperimentRecoveryError("Specify --from-json to rebuild from JSON entries")
    json_dir = Path(args.json_dir).expanduser().resolve()
    parquet_path = Path(args.parquet).expanduser().resolve()
    ensure_layout(parquet_path, json_dir)
    rows = _rebuild_from_json(parquet_path, json_dir, args.dry_run)
    print(f"Rebuilt experiment history with {rows} rows -> {parquet_path}")
    return 0


def main() -> int:  # pragma: no cover - CLI entry
    try:
        return recover_history()
    except ExperimentRecoveryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover - CLI wiring
    sys.exit(main())
