#!/usr/bin/env python3
"""Helper to run a grid search cycle and summarise top-performing parameter sets."""
from __future__ import annotations
import argparse
import json
import os
import sys
from pathlib import Path
from typing import List, Dict, Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_grid
from scripts import rebuild_runs_index
from scripts.config_utils import build_runner_config


def parse_cli(argv=None):
    parser = argparse.ArgumentParser(description="Run grid search and report top parameter sets")
    parser.add_argument("--top-k", type=int, default=5, help="Number of top results to include in the report")
    parser.add_argument("--min-trades", type=int, default=0, help="Minimum trade count filter when ranking")
    parser.add_argument("--rebuild-index", action="store_true", help="Rebuild runs/index.csv after grid execution")
    parser.add_argument("--report", default=None, help="Optional path to write JSON summary")
    parser.add_argument("--runs-dir", default="runs", help="Directory where run outputs are stored")
    parser.add_argument("--dry-run", action="store_true", help="Skip executing the grid and only summarise existing results")
    args, grid_argv = parser.parse_known_args(argv)
    return args, grid_argv


def load_index_rows(index_path: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not os.path.exists(index_path):
        return rows
    import csv
    with open(index_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def normalise_row(row: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(row)
    for key in ("trades", "wins"):
        try:
            out[key] = int(float(out.get(key, 0) or 0))
        except Exception:
            out[key] = 0
    for key in ("total_pips",):
        try:
            out[key] = float(out.get(key, 0.0) or 0.0)
        except Exception:
            out[key] = 0.0
    return out


def filter_and_rank(rows: List[Dict[str, Any]], symbol: str | None, mode: str | None, min_trades: int, top_k: int):
    filtered = []
    for row in rows:
        r = normalise_row(row)
        if symbol and r.get("symbol") and r["symbol"] != symbol:
            continue
        if mode and r.get("mode") and r["mode"] != mode:
            continue
        if r.get("trades", 0) < min_trades:
            continue
        filtered.append(r)
    filtered.sort(key=lambda r: r.get("total_pips", 0.0), reverse=True)
    return filtered[:top_k]


def run_cycle(args, grid_argv):
    symbol = None
    mode = None
    if grid_argv:
        grid_args = run_grid.parse_args(grid_argv)
        symbol = grid_args.symbol
        mode = grid_args.mode
        if not args.dry_run:
            run_grid.run_grid(grid_argv)
    elif not args.dry_run:
        # run_grid will auto-detect CSV if possible even without args
        run_grid.run_grid()
    runs_dir = Path(args.runs_dir)
    if args.rebuild_index:
        rows = rebuild_runs_index.gather_rows(runs_dir)
        rebuild_runs_index.write_index(rows, runs_dir / "index.csv")
    index_path = runs_dir / "index.csv"
    rows = load_index_rows(str(index_path))
    top_rows = filter_and_rank(rows, symbol, mode, args.min_trades, args.top_k)
    summary = {
        "runs_dir": args.runs_dir,
        "index_path": str(index_path),
        "symbol": symbol,
        "mode": mode,
        "top": top_rows,
    }
    if args.report:
        os.makedirs(os.path.dirname(args.report) or ".", exist_ok=True)
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def main(argv=None):
    args, grid_argv = parse_cli(argv)
    run_cycle(args, grid_argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
