#!/usr/bin/env python3
"""
Compare both fill modes (Conservative vs Bridge) on the same CSV input and params.

Outputs a run folder with:
- params.json/csv
- cons.metrics.json / bridge.metrics.json
- daily_compare.csv (date-level side-by-side)
- summary.json (combined)
- Append a row to runs/index.csv with cons/bridge key stats
"""
from __future__ import annotations
import argparse
import csv
import json
import os
import sys
from typing import Any, Dict, List

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts.run_sim import load_bars_csv  # reuse loader
from core.runner import BacktestRunner, RunnerConfig


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Run Conservative and Bridge fills side-by-side over the same CSV")
    p.add_argument("--csv", required=True, help="Path to OHLC5m CSV (with header)")
    p.add_argument("--symbol", required=False, help="Symbol to filter (e.g., USDJPY)")
    p.add_argument("--equity", type=float, default=100000.0, help="Equity amount")
    # gating/params overrides
    p.add_argument("--threshold-lcb", type=float, default=None)
    p.add_argument("--min-or-atr", type=float, default=None)
    p.add_argument("--rv-cuts", default=None, help="Override RV band cuts as 'c1,c2'")
    p.add_argument("--allow-low-rv", action="store_true")
    p.add_argument("--k-tp", type=float, default=None)
    p.add_argument("--k-sl", type=float, default=None)
    p.add_argument("--k-tr", type=float, default=None)
    p.add_argument("--warmup", type=int, default=None)
    # outputs
    p.add_argument("--out-dir", default="runs", help="Base directory to create a compare run folder")
    p.add_argument("--dump-max", type=int, default=200)
    p.add_argument("--prior-alpha", type=float, default=None)
    p.add_argument("--prior-beta", type=float, default=None)
    p.add_argument("--include-expected-slip", action="store_true")
    p.add_argument("--rv-quantile", action="store_true")
    p.add_argument("--load-state", default=None, help="Path to baseline state.json to load before compare")
    return p.parse_args(argv)


def _build_rcfg(args) -> RunnerConfig:
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
    rcfg.allow_low_rv = bool(args.allow_low_rv)
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
    return rcfg


def run_compare(args=None) -> Dict[str, Any]:
    args = parse_args(args)
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
    rcfg = _build_rcfg(args)

    # Prepare runners with debug to collect daily
    cons = BacktestRunner(equity=args.equity, symbol=symbol, runner_cfg=rcfg, debug=True, debug_sample_limit=args.dump_max)
    bridge = BacktestRunner(equity=args.equity, symbol=symbol, runner_cfg=rcfg, debug=True, debug_sample_limit=args.dump_max)
    if args.load_state:
        cons.load_state_file(args.load_state)
        bridge.load_state_file(args.load_state)

    m_cons = cons.run(bars, mode="conservative")
    m_br = bridge.run(bars, mode="bridge")

    # Prepare out dir
    os.makedirs(args.out_dir, exist_ok=True)
    from time import strftime
    run_id = f"compare_{symbol}_{strftime('%Y%m%d_%H%M%S')}"
    run_dir = os.path.join(args.out_dir, run_id)
    os.makedirs(run_dir, exist_ok=True)

    params = {
        "csv": args.csv, "symbol": symbol, "equity": args.equity,
        "threshold_lcb": args.threshold_lcb, "min_or_atr": args.min_or_atr,
        "rv_cuts": args.rv_cuts, "allow_low_rv": args.allow_low_rv,
        "k_tp": args.k_tp, "k_sl": args.k_sl, "k_tr": args.k_tr, "warmup": args.warmup,
    }
    with open(os.path.join(run_dir, "params.json"), "w") as f:
        json.dump(params, f, ensure_ascii=False, indent=2)
    with open(os.path.join(run_dir, "cons.metrics.json"), "w") as f:
        json.dump(m_cons.as_dict() | {"debug": getattr(m_cons, 'debug', {})}, f, ensure_ascii=False, indent=2)
    with open(os.path.join(run_dir, "bridge.metrics.json"), "w") as f:
        json.dump(m_br.as_dict() | {"debug": getattr(m_br, 'debug', {})}, f, ensure_ascii=False, indent=2)

    # Daily compare CSV
    daily_cols = [
        "date","fills_cons","fills_bridge","pnl_cons_pips","pnl_bridge_pips","diff_pips",
        "wins_cons","wins_bridge","gate_pass_cons","gate_pass_bridge","ev_pass_cons","ev_pass_bridge"
    ]
    with open(os.path.join(run_dir, "daily_compare.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(daily_cols)
        days = sorted(set((getattr(m_cons, 'daily', {}) or {}).keys()) | set((getattr(m_br, 'daily', {}) or {}).keys()))
        for d in days:
            dc = getattr(m_cons, 'daily', {}).get(d, {})
            db = getattr(m_br, 'daily', {}).get(d, {})
            row = [
                d,
                dc.get("fills",0), db.get("fills",0),
                dc.get("pnl_pips",0.0), db.get("pnl_pips",0.0),
                (dc.get("pnl_pips",0.0) - db.get("pnl_pips",0.0)),
                dc.get("wins",0), db.get("wins",0),
                dc.get("gate_pass",0), db.get("gate_pass",0),
                dc.get("ev_pass",0), db.get("ev_pass",0),
            ]
            w.writerow(row)

    summary = {
        "run_dir": run_dir,
        "symbol": symbol,
        "trades_cons": m_cons.trades,
        "trades_bridge": m_br.trades,
        "wins_cons": m_cons.wins,
        "wins_bridge": m_br.wins,
        "total_pips_cons": m_cons.total_pips,
        "total_pips_bridge": m_br.total_pips,
        "diff_total_pips": m_cons.total_pips - m_br.total_pips,
    }
    with open(os.path.join(run_dir, "summary.json"), "w") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    # Save states
    try:
        with open(os.path.join(run_dir, "cons.state.json"), "w") as f:
            json.dump(cons.export_state(), f, ensure_ascii=False, indent=2)
        with open(os.path.join(run_dir, "bridge.state.json"), "w") as f:
            json.dump(bridge.export_state(), f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    # Append index row
    index_path = os.path.join(args.out_dir, "index.csv")
    write_header = not os.path.exists(index_path)
    with open(index_path, "a", newline="") as f:
        cols = [
            "run_id","run_dir","timestamp","symbol","mode","equity","k_tp","k_sl","k_tr",
            "threshold_lcb","min_or_atr","rv_cuts","allow_low_rv","warmup",
            "trades_cons","wins_cons","total_pips_cons","trades_bridge","wins_bridge","total_pips_bridge","diff_total_pips"
        ]
        w = csv.DictWriter(f, fieldnames=cols)
        if write_header:
            w.writeheader()
        from time import strftime
        w.writerow({
            "run_id": run_id,
            "run_dir": run_dir,
            "timestamp": strftime("%Y%m%d_%H%M%S"),
            "symbol": symbol,
            "mode": "compare",
            "equity": args.equity,
            "k_tp": args.k_tp,
            "k_sl": args.k_sl,
            "k_tr": args.k_tr,
            "threshold_lcb": args.threshold_lcb,
            "min_or_atr": args.min_or_atr,
            "rv_cuts": args.rv_cuts,
            "allow_low_rv": args.allow_low_rv,
            "warmup": args.warmup,
            "trades_cons": m_cons.trades,
            "wins_cons": m_cons.wins,
            "total_pips_cons": m_cons.total_pips,
            "trades_bridge": m_br.trades,
            "wins_bridge": m_br.wins,
            "total_pips_bridge": m_br.total_pips,
            "diff_total_pips": m_cons.total_pips - m_br.total_pips,
        })

    return summary


def main(argv=None):
    out = run_compare(argv)
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
