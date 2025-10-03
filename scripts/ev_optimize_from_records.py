#!/usr/bin/env python3
"""Re-estimate EV profile parameters from run trade records."""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import os
import sys

import pandas as pd

from core.utils import yaml_compat as yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts._time_utils import utcnow_aware
from scripts.ev_vs_actual_pnl import _collect_record_paths, _load_records


@dataclass
class BucketStats:
    trades: int = 0
    hits: int = 0
    pnl_sum: float = 0.0
    ev_sum: float = 0.0

    def update(self, hit: bool, pnl: float, ev_lcb: float) -> None:
        self.trades += 1
        if hit:
            self.hits += 1
        if not math.isnan(pnl):
            self.pnl_sum += pnl
        if not math.isnan(ev_lcb):
            self.ev_sum += ev_lcb


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Re-estimate EV profile using trade outcomes")
    parser.add_argument("--runs-dir", default="runs", help="Directory containing run subfolders")
    parser.add_argument("--strategy", default="day_orb_5m.DayORB5m", help="Strategy class module.Class")
    parser.add_argument("--symbol", default="USDJPY", help="Symbol identifier")
    parser.add_argument("--mode", default="conservative", help="Mode identifier")
    parser.add_argument("--alpha-prior", type=float, default=1.0, help="Beta prior alpha")
    parser.add_argument("--beta-prior", type=float, default=1.0, help="Beta prior beta")
    parser.add_argument("--output-yaml", default=None, help="Optional path to write updated YAML profile")
    parser.add_argument("--output-json", default=None, help="Optional path to write JSON summary")
    parser.add_argument("--min-trades", type=int, default=5, help="Minimum trades per bucket to include in profile")
    parser.add_argument("--quiet", action="store_true", help="Suppress stdout output")
    return parser.parse_args()


def determine_hit(row: pd.Series) -> bool:
    exit_reason = str(row.get("exit", "")).strip().lower()
    if exit_reason:
        return exit_reason == "tp"
    pnl = row.get("pnl_pips")
    if pd.isna(pnl):
        return False
    return float(pnl) > 0


def aggregate_records(record_paths: Iterable[Path]) -> Dict[str, BucketStats]:
    stats: Dict[str, BucketStats] = defaultdict(BucketStats)
    for path in record_paths:
        df = _load_records(path)
        if df.empty:
            continue
        trade_mask = df["pnl_pips"].notna()
        trades = df.loc[trade_mask].copy()
        if trades.empty:
            continue
        if "ts" in trades.columns:
            trades = trades.sort_values("ts")
        for _, row in trades.iterrows():
            session = row.get("session")
            spread = row.get("spread_band")
            rv_band = row.get("rv_band")
            if not (isinstance(session, str) and isinstance(spread, str) and isinstance(rv_band, str)):
                continue
            key = f"{session}:{spread}:{rv_band}"
            hit = determine_hit(row)
            pnl = float(row.get("pnl_pips", float("nan")))
            ev_lcb = float(row.get("ev_lcb", float("nan")))
            stats[key].update(hit, pnl, ev_lcb)
    return stats


def build_profile(
    stats: Dict[str, BucketStats],
    *,
    alpha_prior: float,
    beta_prior: float,
    min_trades: int,
    strategy: str,
    symbol: str,
    mode: str,
    runs_count: int,
) -> Dict:
    buckets_output: List[Dict] = []
    total_trades = sum(stat.trades for stat in stats.values())
    total_hits = sum(stat.hits for stat in stats.values())
    total_ev = sum(stat.ev_sum for stat in stats.values())
    total_pnl = sum(stat.pnl_sum for stat in stats.values())

    for key in sorted(stats.keys()):
        stat = stats[key]
        if stat.trades < min_trades:
            continue
        session, spread, rv_band = key.split(":", 2)
        alpha = alpha_prior + stat.hits
        beta = beta_prior + (stat.trades - stat.hits)
        total = alpha + beta
        p_mean = alpha / total if total > 0 else 0.0
        buckets_output.append(
            {
                "bucket": {
                    "session": session,
                    "spread_band": spread,
                    "rv_band": rv_band,
                },
                "stats": {
                    "trades": stat.trades,
                    "hits": stat.hits,
                    "hit_rate": stat.hits / stat.trades if stat.trades else 0.0,
                    "alpha": alpha,
                    "beta": beta,
                    "p_mean": p_mean,
                    "pnl_avg": stat.pnl_sum / stat.trades if stat.trades else 0.0,
                    "ev_lcb_avg": stat.ev_sum / stat.trades if stat.trades else 0.0,
                },
            }
        )

    global_alpha = alpha_prior + total_hits
    global_beta = beta_prior + (total_trades - total_hits)
    global_total = global_alpha + global_beta
    global_mean = global_alpha / global_total if global_total > 0 else 0.0

    profile = {
        "meta": {
            "strategy": strategy,
            "symbol": symbol,
            "mode": mode,
            "generated_at": utcnow_aware(dt_cls=datetime).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "runs_used": runs_count,
            "total_trades": total_trades,
            "alpha_prior": alpha_prior,
            "beta_prior": beta_prior,
        },
        "global": {
            "alpha": global_alpha,
            "beta": global_beta,
            "p_mean": global_mean,
            "trades": total_trades,
            "hits": total_hits,
            "pnl_sum": total_pnl,
            "ev_lcb_sum": total_ev,
        },
        "buckets": buckets_output,
    }
    return profile


def main() -> None:
    args = parse_args()
    runs_dir = Path(args.runs_dir).expanduser().resolve()
    record_paths = _collect_record_paths(runs_dir)
    if not record_paths:
        raise SystemExit(f"No records.csv files found under {runs_dir}")

    stats = aggregate_records(record_paths)
    profile = build_profile(
        stats,
        alpha_prior=args.alpha_prior,
        beta_prior=args.beta_prior,
        min_trades=args.min_trades,
        strategy=args.strategy,
        symbol=args.symbol,
        mode=args.mode,
        runs_count=len(record_paths),
    )

    summary_json = json.dumps(profile, ensure_ascii=False, indent=2)
    if not args.quiet:
        print(summary_json)

    if args.output_json:
        out_json = Path(args.output_json)
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(summary_json, encoding="utf-8")

    if args.output_yaml:
        out_yaml = Path(args.output_yaml)
        out_yaml.parent.mkdir(parents=True, exist_ok=True)
        with out_yaml.open("w", encoding="utf-8") as f:
            yaml.safe_dump(profile, f, allow_unicode=True, sort_keys=False)


if __name__ == "__main__":
    main()
