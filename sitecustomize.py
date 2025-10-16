"""Test harness bootstrap for optional dependencies."""
from __future__ import annotations

try:
    import importlib
    import pyarrow  # type: ignore[import-not-found]
except ModuleNotFoundError:
    pass
else:
    try:
        importlib.import_module("pyarrow.parquet")
    except ModuleNotFoundError:
        pass
