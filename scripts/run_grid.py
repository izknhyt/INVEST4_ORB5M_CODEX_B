#!/usr/bin/env python3
"""
Small grid-search runner for N_or × k_tp × k_sl.

Runs each combination with the same CSV/symbol/equity and gating params,
saving a separate run folder under --out-dir and appending to runs/index.csv.

Usage example:
  python3 -m scripts.run_grid \
    --csv data/ohlc5m.csv --symbol USDJPY --equity 100000 \
    --or-n 6 --k-tp 0.8,1.0,1.2 --k-sl 0.6,0.8 \
    --threshold-lcb 0.2 --out-dir runs/
"""
from __future__ import annotations
import argparse
import csv
import json
import os
import sys
from dataclasses import replace
from itertools import product
from time import strftime
from typing import List, Dict, Any

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts.run_sim import load_bars_csv
from scripts.config_utils import build_runner_config
from core.runner import BacktestRunner, RunnerConfig


def parse_list_floats(s: str) -> List[float]:
    return [float(x.strip()) for x in s.split(",") if x.strip()]


def parse_list_ints(s: str) -> List[int]:
    return [int(x.strip()) for x in s.split(",") if x.strip()]


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Grid search over N_or × k_tp × k_sl")
    p.add_argument("--csv", required=False, default=None)
    p.add_argument("--symbol", required=False)
    p.add_argument("--equity", type=float, default=100000.0)
    p.add_argument("--mode", default="conservative", choices=["conservative","bridge"])
    # grid params
    p.add_argument("--or-n", default="6", help="Comma-separated N_or values, e.g., '4,6,8'")
    p.add_argument("--k-tp", default="1.0", help="Comma-separated k_tp values, e.g., '0.8,1.0,1.2'")
    p.add_argument("--k-sl", default="0.8", help="Comma-separated k_sl values, e.g., '0.6,0.8,1.0'")
    # gating overrides
    p.add_argument("--threshold-lcb", type=float, default=None)
    p.add_argument("--min-or-atr", type=float, default=None)
    p.add_argument("--rv-cuts", default=None)
    p.add_argument("--allow-low-rv", action="store_true")
    p.add_argument("--allowed-sessions", default="LDN,NY")
    p.add_argument("--warmup", type=int, default=None)
    # outputs
    p.add_argument("--out-dir", default="runs")
    p.add_argument("--dump-daily", action="store_true", help="Save daily.csv for each run")
    p.add_argument("--quiet", action="store_true", help="Suppress progress output")
    p.add_argument("--prior-alpha", type=float, default=None)
    p.add_argument("--prior-beta", type=float, default=None)
    p.add_argument("--include-expected-slip", action="store_true")
    p.add_argument("--rv-quantile", action="store_true")
    p.add_argument("--calibrate-days", type=int, default=None)
    p.add_argument("--load-state", default=None, help="Path to baseline state.json to load for each trial")
    p.add_argument("--ev-mode", default=None, choices=["lcb","off","mean"])
    p.add_argument("--size-floor", type=float, default=None)
    return p.parse_args(argv)


def build_rcfg(args) -> RunnerConfig:
    return build_runner_config(args)


def save_run(out_dir: str, symbol: str, mode: str, params: Dict[str,Any], metrics, state: Dict[str,Any] | None = None) -> str:
    os.makedirs(out_dir, exist_ok=True)
    run_id = f"grid_{symbol}_{mode}_or{params['or_n']}_ktp{params['k_tp']}_ksl{params['k_sl']}_{strftime('%Y%m%d_%H%M%S')}"
    run_dir = os.path.join(out_dir, run_id)
    os.makedirs(run_dir, exist_ok=True)

    # params
    with open(os.path.join(run_dir, "params.json"), "w") as f:
        json.dump(params, f, ensure_ascii=False, indent=2)
    with open(os.path.join(run_dir, "metrics.json"), "w") as f:
        json.dump(metrics.as_dict() | {"debug": getattr(metrics,'debug',{})}, f, ensure_ascii=False, indent=2)
    # save state.json when provided
    state_path = None
    if state is not None:
        state_path = os.path.join(run_dir, "state.json")
        try:
            with open(state_path, "w") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
        except Exception:
            state_path = None
    # optional daily dump
    if getattr(metrics, 'daily', None):
        with open(os.path.join(run_dir, "daily.csv"), "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["date","breakouts","gate_pass","gate_block","ev_pass","ev_reject","fills","wins","pnl_pips"])
            for d in sorted(metrics.daily.keys()):
                dd = metrics.daily[d]
                w.writerow([d, dd.get("breakouts",0), dd.get("gate_pass",0), dd.get("gate_block",0), dd.get("ev_pass",0), dd.get("ev_reject",0), dd.get("fills",0), dd.get("wins",0), dd.get("pnl_pips",0.0)])

    # append index
    index_path = os.path.join(out_dir, "index.csv")
    write_header = not os.path.exists(index_path)
    with open(index_path, "a", newline="") as f:
        cols = [
            "run_id","run_dir","timestamp","symbol","mode","equity","or_n","k_tp","k_sl",
            "threshold_lcb","min_or_atr","rv_cuts","allow_low_rv","warmup",
            "trades","wins","total_pips","state_path","state_loaded","state_archive_path","ev_profile_path"
        ]
        w = csv.DictWriter(f, fieldnames=cols)
        if write_header:
            w.writeheader()
        w.writerow({
            "run_id": run_id,
            "run_dir": run_dir,
            "timestamp": strftime("%Y%m%d_%H%M%S"),
            "symbol": symbol,
            "mode": mode,
            "equity": params.get("equity"),
            "or_n": params.get("or_n"),
            "k_tp": params.get("k_tp"),
            "k_sl": params.get("k_sl"),
            "threshold_lcb": params.get("threshold_lcb"),
            "min_or_atr": params.get("min_or_atr"),
            "rv_cuts": params.get("rv_cuts"),
            "allow_low_rv": params.get("allow_low_rv"),
            "warmup": params.get("warmup"),
            "trades": metrics.trades,
            "wins": metrics.wins,
            "total_pips": metrics.total_pips,
            "state_path": state_path,
            "state_loaded": "",
            "state_archive_path": "",
            "ev_profile_path": "",
        })
    return run_dir


def _fmt_dur(sec: float) -> str:
    if sec < 0:
        sec = 0
    m, s = divmod(int(sec + 0.5), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:d}h{m:02d}m{s:02d}s"
    if m > 0:
        return f"{m:d}m{s:02d}s"
    return f"{s:d}s"


def run_grid(argv=None) -> Dict[str,Any]:
    args = parse_args(argv)
    # Resolve CSV path (auto-detect from data/ if not provided)
    if not args.csv:
        data_dir = os.path.join(ROOT, "data")
        candidates = []
        if os.path.isdir(data_dir):
            for fn in os.listdir(data_dir):
                if fn.lower().endswith(".csv"):
                    candidates.append(os.path.join("data", fn))
        if len(candidates) == 1:
            args.csv = candidates[0]
        else:
            return {"error": "csv_not_specified", "suggestions": candidates[:5]}
    # Friendly check for CSV existence
    if not os.path.exists(args.csv):
        suggestions: List[str] = []
        data_dir = os.path.join(ROOT, "data")
        if os.path.isdir(data_dir):
            for fn in os.listdir(data_dir):
                if fn.lower().endswith(".csv"):
                    suggestions.append(os.path.join("data", fn))
        return {"error": "csv_not_found", "path": args.csv, "suggestions": suggestions[:5]}
    bars = list(load_bars_csv(args.csv, symbol=args.symbol, strict=False))
    if not bars:
        return {"error": "no bars"}
    symbol = args.symbol or bars[0].get("symbol")
    rcfg_base = build_rcfg(args)

    or_vals = parse_list_ints(args.or_n)
    ktp_vals = parse_list_floats(args.k_tp)
    ksl_vals = parse_list_floats(args.k_sl)

    combos = list(product(or_vals, ktp_vals, ksl_vals))
    total = len(combos)
    start_ts = __import__("time").time()
    results: List[Dict[str,Any]] = []
    for idx, (or_n, k_tp, k_sl) in enumerate(combos, 1):
        if not args.quiet:
            elapsed = __import__("time").time() - start_ts
            avg = elapsed / max(1, (idx - 1)) if idx > 1 else 0
            eta = avg * (total - idx)
            msg = (
                f"[{idx}/{total}] or_n={or_n} k_tp={k_tp} k_sl={k_sl} "
                f"elapsed={_fmt_dur(elapsed)} ETA={_fmt_dur(eta)}"
            )
            print(msg, file=sys.stderr, flush=True)
        strategy_cfg = replace(rcfg_base.strategy, or_n=or_n, k_tp=k_tp, k_sl=k_sl)
        rcfg = replace(
            rcfg_base,
            strategy=strategy_cfg,
            ev_mode=(args.ev_mode or rcfg_base.ev_mode),
            size_floor_mult=(args.size_floor if args.size_floor is not None else rcfg_base.size_floor_mult),
        )
        runner = BacktestRunner(equity=args.equity, symbol=symbol, runner_cfg=rcfg, debug=args.dump_daily, debug_sample_limit=0)
        if args.load_state:
            runner.load_state_file(args.load_state)
        metrics = runner.run(bars, mode=args.mode)
        params = {
            "csv": args.csv, "symbol": symbol, "equity": args.equity,
            "mode": args.mode, "or_n": or_n, "k_tp": k_tp, "k_sl": k_sl,
            "threshold_lcb": args.threshold_lcb, "min_or_atr": args.min_or_atr,
            "rv_cuts": args.rv_cuts, "allow_low_rv": args.allow_low_rv, "allowed_sessions": args.allowed_sessions,
            "warmup": args.warmup,
        }
        # export state for index and persistence
        state_blob = None
        try:
            state_blob = runner.export_state()
        except Exception:
            state_blob = None
        run_dir = save_run(args.out_dir, symbol, args.mode, params, metrics, state_blob)

        results.append({
            "or_n": or_n, "k_tp": k_tp, "k_sl": k_sl,
            "trades": metrics.trades, "wins": metrics.wins, "total_pips": metrics.total_pips,
            "run_dir": run_dir,
        })

    # summary
    summary = {
        "runs": len(results),
        "best_by_total_pips": sorted(results, key=lambda r: r["total_pips"], reverse=True)[:5],
        "out_dir": args.out_dir,
        "mode": args.mode,
    }
    print(json.dumps(summary, ensure_ascii=False))
    return summary


def main(argv=None):
    run_grid(argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
