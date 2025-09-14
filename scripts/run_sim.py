#!/usr/bin/env python3
"""
Minimal simulation CLI for MVP

Usage:
  python3 scripts/run_sim.py --csv path/to/ohlc5m.csv --symbol USDJPY --mode conservative --equity 100000 --json-out out.json

CSV columns (header required): timestamp,symbol,tf,o,h,l,c,v,spread
Outputs JSON metrics: {"trades":.., "wins":.., "total_pips":..}
"""
from __future__ import annotations
import argparse
import csv
import json
from typing import List, Dict, Any

import os
import sys

# Ensure project root is on sys.path when running as a script
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.runner import BacktestRunner, RunnerConfig


def load_bars_csv(path: str) -> List[Dict[str, Any]]:
    bars: List[Dict[str, Any]] = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                bar = {
                    "timestamp": row["timestamp"],
                    "symbol": row["symbol"],
                    "tf": row.get("tf", "5m"),
                    "o": float(row["o"]),
                    "h": float(row["h"]),
                    "l": float(row["l"]),
                    "c": float(row["c"]),
                    "v": float(row.get("v", 0.0)),
                    "spread": float(row.get("spread", 0.0)),
                }
            except (KeyError, ValueError):
                continue
            bars.append(bar)
    return bars


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Run minimal ORB 5m simulation over CSV")
    p.add_argument("--csv", required=False, default=None, help="Path to OHLC5m CSV (with header)")
    p.add_argument("--symbol", required=False, help="Symbol to filter (e.g., USDJPY)")
    p.add_argument("--mode", default="conservative", choices=["conservative", "bridge"], help="Fill mode")
    p.add_argument("--equity", type=float, default=100000.0, help="Equity amount")
    p.add_argument("--json-out", default=None, help="Write metrics JSON to file (default: stdout)")
    p.add_argument("--threshold-lcb", type=float, default=None, help="Override EV_LCB threshold in pips (e.g., 0.0 for warmup)")
    p.add_argument("--debug", action="store_true", help="Print debug counters (reasons for no trades)")
    p.add_argument("--min-or-atr", type=float, default=None, help="Override min OR/ATR ratio gate (e.g., 0.4)")
    p.add_argument("--rv-cuts", default=None, help="Override RV band cuts as 'c1,c2' (e.g., 0.005,0.015)")
    p.add_argument("--allow-low-rv", action="store_true", help="Allow rv_band=low to pass router gate")
    p.add_argument("--k-tp", type=float, default=None, help="Override k_tp (TP in ATR multiples)")
    p.add_argument("--k-sl", type=float, default=None, help="Override k_sl (SL in ATR multiples)")
    p.add_argument("--k-tr", type=float, default=None, help="Override k_tr (trail in ATR multiples)")
    p.add_argument("--warmup", type=int, default=None, help="Bypass EV gate for first N signals")
    p.add_argument("--prior-alpha", type=float, default=None, help="Beta prior alpha for EV gate")
    p.add_argument("--prior-beta", type=float, default=None, help="Beta prior beta for EV gate")
    p.add_argument("--include-expected-slip", action="store_true", help="Include expected slippage in realized cost")
    p.add_argument("--rv-quantile", action="store_true", help="Enable RV band session-quantile calibration")
    p.add_argument("--calibrate-days", type=int, default=None, help="Number of initial days to calibrate EV (no trading)")
    p.add_argument("--ev-mode", default=None, choices=["lcb","off","mean"], help="EV mode: lcb (default), off, mean")
    p.add_argument("--size-floor", type=float, default=None, help="Size floor multiplier when ev-mode=off (default 0.01)")
    p.add_argument("--dump-csv", default=None, help="Write detailed sample records CSV (path)")
    p.add_argument("--dump-max", type=int, default=200, help="Max number of sample records to dump")
    p.add_argument("--dump-daily", default=None, help="Write daily funnel CSV (path)")
    p.add_argument("--out-dir", default=None, help="Base directory to store a run folder with params + metrics + dumps (e.g., runs/)")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    # Resolve CSV path (allow auto-detect from data/ if not provided)
    if not args.csv:
        import os as _os
        data_dir = _os.path.join(ROOT, "data")
        candidates = []
        if _os.path.isdir(data_dir):
            for fn in _os.listdir(data_dir):
                if fn.lower().endswith(".csv"):
                    candidates.append(_os.path.join("data", fn))
        if len(candidates) == 1:
            args.csv = candidates[0]
        else:
            print(json.dumps({"error":"csv_not_specified","suggestions":candidates[:5]}))
            return 1
    bars = load_bars_csv(args.csv)
    if args.symbol:
        bars = [b for b in bars if b.get("symbol") == args.symbol]
    if not bars:
        print(json.dumps({"error": "no bars"}))
        return 1
    symbol = args.symbol or bars[0].get("symbol")
    rcfg = RunnerConfig()
    if args.threshold_lcb is not None:
        rcfg.threshold_lcb_pip = args.threshold_lcb
    if args.min_or_atr is not None:
        rcfg.min_or_atr_ratio = args.min_or_atr
    if args.rv_cuts:
        try:
            c1, c2 = [float(x.strip()) for x in args.rv_cuts.split(",")]
            rcfg.rv_band_cuts = [c1, c2]
        except Exception:
            pass
    if args.allow_low_rv:
        rcfg.allow_low_rv = True
    if args.k_tp is not None:
        rcfg.k_tp = args.k_tp
    if args.k_sl is not None:
        rcfg.k_sl = args.k_sl
    if args.k_tr is not None:
        rcfg.k_tr = args.k_tr
    if args.warmup is not None:
        rcfg.warmup_trades = args.warmup
    if args.prior_alpha is not None:
        rcfg.prior_alpha = args.prior_alpha
    if args.prior_beta is not None:
        rcfg.prior_beta = args.prior_beta
    if args.include_expected_slip:
        rcfg.include_expected_slip = True
    if args.rv_quantile:
        rcfg.rv_qcalib_enabled = True
    if args.calibrate_days is not None:
        rcfg.calibrate_days = args.calibrate_days
    if args.ev_mode is not None:
        rcfg.ev_mode = args.ev_mode
    if args.size_floor is not None:
        rcfg.size_floor_mult = args.size_floor
    debug_for_dump = args.debug or bool(args.dump_csv) or bool(args.dump_daily) or bool(args.out_dir)
    runner = BacktestRunner(equity=args.equity, symbol=symbol, runner_cfg=rcfg, debug=debug_for_dump, debug_sample_limit=args.dump_max)
    metrics = runner.run(bars, mode=args.mode)
    out = metrics.as_dict()
    if getattr(metrics, 'debug', None):
        out["debug"] = metrics.debug
    # Write dumps if requested
    if args.dump_csv and getattr(metrics, 'records', None):
        # Determine header
        import csv as _csv
        recs = metrics.records
        header = sorted({k for r in recs for k in r.keys()})
        with open(args.dump_csv, "w", newline="") as f:
            w = _csv.DictWriter(f, fieldnames=header)
            w.writeheader()
            for r in recs[: args.dump_max]:
                w.writerow(r)
        out["dump_csv"] = args.dump_csv
        out["dump_rows"] = min(len(recs), args.dump_max)
    if args.dump_daily and getattr(metrics, 'daily', None):
        import csv as _csv
        daily = metrics.daily
        cols = ["date","breakouts","gate_pass","gate_block","ev_pass","ev_reject","fills","wins","pnl_pips"]
        with open(args.dump_daily, "w", newline="") as f:
            w = _csv.writer(f)
            w.writerow(cols)
            for d in sorted(daily.keys()):
                dd = daily[d]
                w.writerow([d, dd.get("breakouts",0), dd.get("gate_pass",0), dd.get("gate_block",0), dd.get("ev_pass",0), dd.get("ev_reject",0), dd.get("fills",0), dd.get("wins",0), dd.get("pnl_pips",0.0)])
        out["dump_daily"] = args.dump_daily

    # Save a run folder with parameters + metrics (+ dumps)
    if args.out_dir:
        import os as _os, json as _json, csv as _csv, hashlib as _hashlib, time as _time
        base = args.out_dir
        _os.makedirs(base, exist_ok=True)
        # build run id
        ts_id = _time.strftime("%Y%m%d_%H%M%S")
        id_str = f"{symbol}_{args.mode}_{ts_id}"
        run_dir = _os.path.join(base, id_str)
        _os.makedirs(run_dir, exist_ok=True)

        # capture parameters
        params = {
            "csv": args.csv,
            "symbol": symbol,
            "mode": args.mode,
            "equity": args.equity,
            "threshold_lcb": args.threshold_lcb,
            "min_or_atr": args.min_or_atr,
            "rv_cuts": args.rv_cuts,
            "allow_low_rv": args.allow_low_rv,
            "k_tp": args.k_tp,
            "k_sl": args.k_sl,
            "k_tr": args.k_tr,
            "warmup": args.warmup,
            "dump_max": args.dump_max,
        }
        # write params.json and params.csv
        with open(_os.path.join(run_dir, "params.json"), "w") as f:
            _json.dump(params, f, ensure_ascii=False, indent=2)
        with open(_os.path.join(run_dir, "params.csv"), "w", newline="") as f:
            w = _csv.DictWriter(f, fieldnames=list(params.keys()))
            w.writeheader(); w.writerow(params)

        # write metrics.json
        with open(_os.path.join(run_dir, "metrics.json"), "w") as f:
            _json.dump(out, f, ensure_ascii=False, indent=2)

        # also store dumps if available (or create from in-memory metrics)
        # detailed records
        recs_path = _os.path.join(run_dir, "records.csv")
        if getattr(metrics, 'records', None):
            import csv as _csv
            header = sorted({k for r in metrics.records for k in r.keys()})
            with open(recs_path, "w", newline="") as f:
                w = _csv.DictWriter(f, fieldnames=header)
                w.writeheader()
                for r in metrics.records[: args.dump_max]:
                    w.writerow(r)
        elif args.dump_csv:
            # If user wrote their own file, copy it
            try:
                import shutil as _shutil
                _shutil.copy(args.dump_csv, recs_path)
            except Exception:
                pass

        # daily funnel
        daily_path = _os.path.join(run_dir, "daily.csv")
        if getattr(metrics, 'daily', None):
            cols = ["date","breakouts","gate_pass","gate_block","ev_pass","ev_reject","fills","wins","pnl_pips"]
            with open(daily_path, "w", newline="") as f:
                w = _csv.writer(f)
                w.writerow(cols)
                for d in sorted(metrics.daily.keys()):
                    dd = metrics.daily[d]
                    w.writerow([d, dd.get("breakouts",0), dd.get("gate_pass",0), dd.get("gate_block",0), dd.get("ev_pass",0), dd.get("ev_reject",0), dd.get("fills",0), dd.get("wins",0), dd.get("pnl_pips",0.0)])
        elif args.dump_daily:
            try:
                import shutil as _shutil
                _shutil.copy(args.dump_daily, daily_path)
            except Exception:
                pass

        out["run_dir"] = run_dir
        # Save state.json
        try:
            state_path = os.path.join(run_dir, "state.json")
            st = runner.export_state()
            with open(state_path, "w") as f:
                json.dump(st, f, ensure_ascii=False, indent=2)
            out["state_path"] = state_path
        except Exception:
            pass

        # Append or create runs index CSV summarizing this run
        index_path = _os.path.join(base, "index.csv")
        row = {
            "run_id": id_str,
            "run_dir": run_dir,
            "timestamp": ts_id,
            "symbol": symbol,
            "mode": args.mode,
            "equity": args.equity,
            "k_tp": args.k_tp,
            "k_sl": args.k_sl,
            "k_tr": args.k_tr,
            "threshold_lcb": args.threshold_lcb,
            "min_or_atr": args.min_or_atr,
            "rv_cuts": args.rv_cuts,
            "allow_low_rv": args.allow_low_rv,
            "warmup": args.warmup,
            "trades": out.get("trades"),
            "wins": out.get("wins"),
            "total_pips": out.get("total_pips"),
            "win_rate": (out.get("wins",0)/out.get("trades",1)) if out.get("trades",0) else 0.0,
            "pnl_per_trade": (out.get("total_pips",0.0)/out.get("trades",1)) if out.get("trades",0) else 0.0,
            "gate_block": out.get("debug",{}).get("gate_block"),
            "ev_reject": out.get("debug",{}).get("ev_reject"),
            "ev_bypass": out.get("debug",{}).get("ev_bypass"),
            "dump_rows": out.get("dump_rows"),
        }
        # create or append with header
        import csv as _csv
        write_header = not _os.path.exists(index_path)
        with open(index_path, "a", newline="") as f:
            cols = [
                "run_id","run_dir","timestamp","symbol","mode","equity",
                "k_tp","k_sl","k_tr","threshold_lcb","min_or_atr","rv_cuts","allow_low_rv","warmup",
                "trades","wins","total_pips","win_rate","pnl_per_trade","state_path",
                "gate_block","ev_reject","ev_bypass","dump_rows",
            ]
            w = _csv.DictWriter(f, fieldnames=cols)
            if write_header:
                w.writeheader()
            row["state_path"] = out.get("state_path")
            w.writerow(row)
        out["index_csv"] = index_path
    out_json = json.dumps(out)
    if args.json_out:
        with open(args.json_out, "w") as f:
            f.write(out_json)
    else:
        print(out_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
