#!/usr/bin/env python3
"""Compute evaluation metrics from metrics.json and daily.csv."""
from __future__ import annotations
import argparse
import json
from pathlib import Path

import pandas as pd

def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Compute metrics (Sharpe, maxDD, PF, Expectancy, CAGR)")
    p.add_argument("--metrics", required=True, help="Path to metrics.json")
    p.add_argument("--daily", required=True, help="Path to daily.csv")
    p.add_argument("--equity", type=float, default=100000.0)
    p.add_argument("--years", type=float, default=6.0)
    p.add_argument("--json-out", default=None)
    return p.parse_args(argv)

def max_drawdown(series: pd.Series) -> float:
    cum = series.cumsum()
    peak = cum.cummax()
    drawdown = cum - peak
    return drawdown.min()

def profit_factor(trades_df: pd.DataFrame) -> float:
    wins = trades_df[trades_df['pnl_pips'] > 0]['pnl_pips'].sum()
    losses = trades_df[trades_df['pnl_pips'] < 0]['pnl_pips'].sum()
    if losses == 0 or wins == 0:
        return 0.0
    return wins / abs(losses)

def expectancy(total_pips: float, trades: int) -> float:
    return total_pips / trades if trades else 0.0

def cagr(total_pips: float, equity: float, years: float) -> float:
    final_equity = equity + total_pips  # assuming pip value ~1
    if final_equity <= 0 or equity <= 0:
        return -1.0
    return (final_equity / equity) ** (1 / years) - 1

def main(argv=None) -> int:
    args = parse_args(argv)
    metrics = json.loads(Path(args.metrics).read_text())
    daily = pd.read_csv(args.daily)
    daily_pnl = daily.get('pnl_pips', pd.Series(dtype=float))
    sharpe = daily_pnl.mean() / daily_pnl.std(ddof=0) if daily_pnl.std(ddof=0) else 0.0
    max_dd = max_drawdown(daily_pnl)
    pf = profit_factor(daily)
    exp = expectancy(metrics.get('total_pips', 0.0), metrics.get('trades', 0))
    cagr_val = cagr(metrics.get('total_pips', 0.0), args.equity, args.years)

    result = {
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "profit_factor": pf,
        "expectancy": exp,
        "cagr": cagr_val,
        "input_metrics": metrics,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
