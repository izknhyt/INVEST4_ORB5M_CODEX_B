"""Utilities for the experiment history repository layout."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
HISTORY_ROOT = Path(__file__).resolve().parent
PARQUET_FILENAME = "records.parquet"
PARQUET_PATH = HISTORY_ROOT / PARQUET_FILENAME
RUNS_DIR = HISTORY_ROOT / "runs"

# (column_name, logical_type)
PARQUET_SCHEMA_SPEC: List[Tuple[str, str]] = [
    ("run_id", "string"),
    ("manifest_id", "string"),
    ("mode", "string"),
    ("timestamp_utc", "string"),
    ("commit_sha", "string"),
    ("dataset_sha256", "string"),
    ("dataset_rows", "int64"),
    ("command", "string"),
    ("metrics_path", "string"),
    ("gate_report_path", "string"),
    ("equity", "float64"),
    ("sharpe", "float64"),
    ("max_drawdown", "float64"),
    ("trades", "int64"),
    ("win_rate", "float64"),
    ("ev_gap", "float64"),
    ("gate_block_count", "int64"),
    ("router_gate_count", "int64"),
    ("notes", "string"),
]

PARQUET_COLUMNS: List[str] = [name for name, _ in PARQUET_SCHEMA_SPEC]


def ensure_layout(parquet_path: Path = PARQUET_PATH, runs_dir: Path = RUNS_DIR) -> None:
    """Create the expected directory structure for the experiment history."""
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    runs_dir.mkdir(parents=True, exist_ok=True)


def build_parquet_schema():
    """Return the PyArrow schema for the experiment history table."""
    import pyarrow as pa

    type_map: Dict[str, "pa.DataType"] = {
        "string": pa.string(),
        "int64": pa.int64(),
        "float64": pa.float64(),
    }
    fields = [pa.field(name, type_map[type_name]) for name, type_name in PARQUET_SCHEMA_SPEC]
    return pa.schema(fields)


def rows_to_table(rows: Iterable[Dict[str, object]]):
    """Convert rows into a PyArrow table respecting the schema."""
    import pyarrow as pa

    schema = build_parquet_schema()
    columns: Dict[str, List[object]] = {name: [] for name in PARQUET_COLUMNS}
    for row in rows:
        for name, type_name in PARQUET_SCHEMA_SPEC:
            value = row.get(name)
            if value is None:
                columns[name].append(None)
                continue
            if type_name == "string":
                columns[name].append(str(value))
            elif type_name == "int64":
                try:
                    columns[name].append(int(value))
                except (TypeError, ValueError):
                    columns[name].append(None)
            elif type_name == "float64":
                try:
                    columns[name].append(float(value))
                except (TypeError, ValueError):
                    columns[name].append(None)
            else:
                columns[name].append(value)
    return pa.Table.from_pydict(columns, schema=schema)


def read_parquet(parquet_path: Path = PARQUET_PATH):
    """Read the experiment history table if it exists."""
    import pyarrow.parquet as pq

    if not parquet_path.exists():
        return None
    return pq.read_table(parquet_path)


def write_parquet(table, parquet_path: Path = PARQUET_PATH) -> None:
    """Persist the experiment history table to Parquet."""
    import pyarrow.parquet as pq

    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, parquet_path)


__all__ = [
    "REPO_ROOT",
    "HISTORY_ROOT",
    "PARQUET_PATH",
    "RUNS_DIR",
    "PARQUET_COLUMNS",
    "PARQUET_SCHEMA_SPEC",
    "ensure_layout",
    "rows_to_table",
    "read_parquet",
    "write_parquet",
]
