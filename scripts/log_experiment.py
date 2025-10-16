#!/usr/bin/env python3
"""Append Day ORB backtest results to the experiment history repository."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from experiments.history import (
    REPO_ROOT,
    PARQUET_PATH,
    RUNS_DIR,
    ensure_layout,
    read_parquet,
    rows_to_table,
    write_parquet,
)
from experiments.history.utils import (
    compute_dataset_fingerprint,
    extract_timestamp_iso,
    load_json,
    relative_to_repo,
)


class ExperimentLoggingError(RuntimeError):
    """Raised when experiment logging fails."""


def _parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, help="Backtest run directory (metrics.json required)")
    parser.add_argument("--manifest-id", required=True, help="Logical manifest identifier for the run")
    parser.add_argument("--mode", help="Strategy mode (defaults to params.json value)")
    parser.add_argument("--commit-sha", required=True, help="Git commit hash associated with the run")
    parser.add_argument("--command", help="Command used to launch the run")
    parser.add_argument("--equity", type=float, help="Override equity value from params.json")
    parser.add_argument("--notes", help="Optional operator notes")
    parser.add_argument("--dataset-csv", help="Path to the dataset used for the run")
    parser.add_argument("--dataset-sha256", help="Precomputed dataset SHA256")
    parser.add_argument("--dataset-rows", type=int, help="Precomputed dataset row count")
    parser.add_argument("--parquet", default=str(PARQUET_PATH), help="Experiment history Parquet path")
    parser.add_argument("--json-dir", default=str(RUNS_DIR), help="Directory for per-run JSON entries")
    parser.add_argument("--dry-run", action="store_true", help="Do not write any files")
    return parser.parse_args(argv)


def _require_file(path: Path, description: str) -> None:
    if not path.exists():
        raise ExperimentLoggingError(f"Missing {description}: {path}")


def _load_run_artifacts(run_dir: Path) -> Tuple[Dict[str, Any], Dict[str, Any], Path, Path, Path]:
    metrics_path = run_dir / "metrics.json"
    daily_path = run_dir / "daily.csv"
    records_path = run_dir / "records.csv"
    params_path = run_dir / "params.json"
    _require_file(metrics_path, "metrics.json")
    _require_file(daily_path, "daily.csv")
    _require_file(records_path, "records.csv")
    metrics = load_json(metrics_path)
    params = load_json(params_path) if params_path.exists() else {}
    return metrics, params, metrics_path, daily_path, records_path


def _normalise_path(candidate: Path, run_dir: Path) -> Path:
    if candidate.is_absolute():
        return candidate
    repo_candidate = (REPO_ROOT / candidate).resolve()
    if repo_candidate.exists():
        return repo_candidate
    run_candidate = (run_dir / candidate).resolve()
    if run_candidate.exists():
        return run_candidate
    return (REPO_ROOT / candidate).resolve()


def _resolve_dataset_path(args: argparse.Namespace, params: Dict[str, Any], run_dir: Path) -> Path:
    if args.dataset_csv:
        return _normalise_path(Path(args.dataset_csv), run_dir)
    csv_path = params.get("csv")
    if csv_path:
        return _normalise_path(Path(csv_path), run_dir)
    raise ExperimentLoggingError("Dataset CSV path not found in params.json; specify --dataset-csv")


def _dataset_fingerprint(args: argparse.Namespace, dataset_path: Path) -> Tuple[str, Optional[int]]:
    sha_value = args.dataset_sha256
    rows = args.dataset_rows
    if sha_value is not None and rows is not None:
        return sha_value, rows
    dataset_path = dataset_path.expanduser()
    if not dataset_path.exists():
        raise ExperimentLoggingError(f"Dataset CSV not found: {dataset_path}")
    sha_value, computed_rows = compute_dataset_fingerprint(dataset_path)
    return sha_value, computed_rows


def _extract_debug_counter(metrics: Dict[str, Any], key: str) -> Optional[int]:
    if key in metrics:
        value = metrics.get(key)
        return int(value) if isinstance(value, (int, float)) else None
    debug = metrics.get("debug")
    if isinstance(debug, dict):
        value = debug.get(key)
        if isinstance(value, (int, float)):
            return int(value)
    return None


def _coerce_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _build_row(
    run_id: str,
    manifest_id: str,
    mode: Optional[str],
    commit_sha: str,
    command: Optional[str],
    notes: Optional[str],
    metrics_path: Path,
    daily_path: Path,
    records_path: Path,
    metrics: Dict[str, Any],
    params: Dict[str, Any],
    dataset_path: Path,
    dataset_sha: str,
    dataset_rows: Optional[int],
    equity_override: Optional[float],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    timestamp_utc = extract_timestamp_iso(run_id)
    equity = equity_override if equity_override is not None else _coerce_float(params.get("equity"))
    trades = _coerce_int(metrics.get("trades"))
    wins = _coerce_int(metrics.get("wins"))
    win_rate = None
    if trades and wins is not None:
        win_rate = wins / trades if trades else None
    ev_gap = _coerce_float(metrics.get("ev_gap"))
    if ev_gap is None:
        debug = metrics.get("debug") if isinstance(metrics.get("debug"), dict) else None
        if debug:
            ev_gap = _coerce_float(debug.get("ev_gap"))
    gate_report_path = metrics.get("gate_report_path") or metrics.get("gate_report")
    gate_report_value: Optional[str]
    if isinstance(gate_report_path, str) and gate_report_path:
        gate_report_value = relative_to_repo(_normalise_path(Path(gate_report_path), metrics_path.parent))
    else:
        gate_report_value = gate_report_path if gate_report_path is not None else None
    row: Dict[str, Any] = {
        "run_id": run_id,
        "manifest_id": manifest_id,
        "mode": mode or params.get("mode"),
        "timestamp_utc": timestamp_utc,
        "commit_sha": commit_sha,
        "dataset_sha256": dataset_sha,
        "dataset_rows": dataset_rows,
        "command": command,
        "metrics_path": relative_to_repo(metrics_path),
        "gate_report_path": gate_report_value,
        "equity": equity,
        "sharpe": _coerce_float(metrics.get("sharpe")),
        "max_drawdown": _coerce_float(metrics.get("max_drawdown")),
        "trades": trades,
        "win_rate": win_rate,
        "ev_gap": ev_gap,
        "gate_block_count": _extract_debug_counter(metrics, "gate_block"),
        "router_gate_count": _extract_debug_counter(metrics, "router_gate"),
        "notes": notes,
    }
    artefacts: List[Dict[str, str]] = [
        {"type": "metrics", "path": relative_to_repo(metrics_path)},
        {"type": "daily", "path": relative_to_repo(daily_path)},
        {"type": "records", "path": relative_to_repo(records_path)},
    ]
    params_path = metrics_path.with_name("params.json")
    if params_path.exists():
        artefacts.append({"type": "params", "path": relative_to_repo(params_path)})
    runtime = metrics.get("runtime") if isinstance(metrics.get("runtime"), dict) else {}
    json_payload: Dict[str, Any] = {
        **row,
        "dataset_path": relative_to_repo(dataset_path),
        "daily_path": relative_to_repo(daily_path),
        "records_path": relative_to_repo(records_path),
        "metrics_path": relative_to_repo(metrics_path),
        "params": params,
        "metrics": metrics,
        "artefacts": artefacts,
        "runtime": runtime,
    }
    if dataset_rows is not None:
        json_payload["dataset_rows"] = dataset_rows
    json_payload["dataset_sha256"] = dataset_sha
    return row, json_payload


def _append_to_parquet(parquet_path: Path, row: Dict[str, Any]) -> None:
    try:
        import pyarrow as pa  # type: ignore[import-not-found]
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency guard
        raise ExperimentLoggingError(
            "PyArrow is required to append experiment history rows. Install it via `pip install pyarrow`."
        ) from exc

    try:
        current_table = read_parquet(parquet_path)
        new_table = rows_to_table([row])
    except ModuleNotFoundError as exc:
        raise ExperimentLoggingError(
            "PyArrow is required to manage experiment history Parquet files. Install it via `pip install pyarrow`."
        ) from exc

    if current_table is not None:
        combined = pa.concat_tables([current_table, new_table])
    else:
        combined = new_table

    try:
        write_parquet(combined, parquet_path)
    except ModuleNotFoundError as exc:
        raise ExperimentLoggingError(
            "PyArrow is required to persist experiment history Parquet files. Install it via `pip install pyarrow`."
        ) from exc


def _check_duplicate(parquet_path: Path, json_path: Path, run_id: str) -> None:
    current_table = read_parquet(parquet_path)
    if current_table is not None:
        existing_ids = set(current_table.column("run_id").to_pylist())
        if run_id in existing_ids:
            raise ExperimentLoggingError(f"Run {run_id} already exists in {parquet_path}")
    if json_path.exists():
        raise ExperimentLoggingError(f"Run JSON already exists: {json_path}")


def log_experiment(argv: Optional[Iterable[str]] = None) -> int:
    args = _parse_args(argv)
    run_dir = Path(args.run_dir).expanduser().resolve()
    if not run_dir.exists():
        raise ExperimentLoggingError(f"Run directory not found: {run_dir}")
    metrics, params, metrics_path, daily_path, records_path = _load_run_artifacts(run_dir)
    dataset_path = _resolve_dataset_path(args, params, run_dir)
    dataset_sha, dataset_rows = _dataset_fingerprint(args, dataset_path)
    row, json_payload = _build_row(
        run_dir.name,
        args.manifest_id,
        args.mode,
        args.commit_sha,
        args.command,
        args.notes,
        metrics_path,
        daily_path,
        records_path,
        metrics,
        params,
        dataset_path,
        dataset_sha,
        dataset_rows,
        args.equity,
    )

    json_dir = Path(args.json_dir).expanduser().resolve()
    parquet_path = Path(args.parquet).expanduser().resolve()
    ensure_layout(parquet_path, json_dir)
    json_path = json_dir / f"{run_dir.name}.json"

    if args.dry_run:
        print(json.dumps({"row": row, "json": json_payload}, indent=2))
        return 0

    _check_duplicate(parquet_path, json_path, run_dir.name)
    _append_to_parquet(parquet_path, row)
    with json_path.open("w") as handle:
        json.dump(json_payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(f"Logged experiment {run_dir.name} -> {relative_to_repo(json_path)}")
    return 0


def main() -> int:  # pragma: no cover - CLI entry point
    try:
        return log_experiment()
    except ExperimentLoggingError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover - CLI wiring
    sys.exit(main())
