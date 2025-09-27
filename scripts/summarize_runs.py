#!/usr/bin/env python3
"""Summarize runs/index.csv with additional metrics."""
from __future__ import annotations
import argparse
import json
from pathlib import Path

import pandas as pd

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.utils_runs import load_runs_index


def compute_sharpe(pnl_series: pd.Series) -> float:
    if pnl_series.std(ddof=0) == 0:
        return 0.0
    return pnl_series.mean() / pnl_series.std(ddof=0)


def summarize(runs_df: pd.DataFrame) -> dict:
    total_pips = runs_df['total_pips'].sum()
    trades = runs_df['trades'].sum()
    wins = runs_df['wins'].sum()
    win_rate = wins / trades if trades else 0.0
    return {
        'runs': len(runs_df),
        'total_pips': total_pips,
        'trades': trades,
        'wins': wins,
        'win_rate': win_rate,
    }


def daily_sharpe(run_dir: Path) -> float:
    daily_csv = run_dir / 'daily.csv'
    if not daily_csv.exists():
        return 0.0
    df = pd.read_csv(daily_csv)
    if 'pnl_pips' not in df:
        return 0.0
    return compute_sharpe(df['pnl_pips'])


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Summarize runs/index.csv")
    p.add_argument("--runs-dir", default="runs")
    p.add_argument("--json-out", default=None)
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    records = load_runs_index(Path(args.runs_dir) / "index.csv")
    df = pd.DataFrame([r.__dict__ for r in records])
    summary = {k: (float(v) if hasattr(v, 'item') else v) for k, v in summarize(df).items()}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
