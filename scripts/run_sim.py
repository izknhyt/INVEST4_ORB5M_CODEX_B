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
import subprocess

from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import os
import sys

# Ensure project root is on sys.path when running as a script
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.utils import yaml_compat as yaml
from core.runner import BacktestRunner
from scripts.config_utils import build_runner_config


def _strategy_state_key(strategy_cls) -> str:
    module = getattr(strategy_cls, "__module__", "strategy") or "strategy"
    if module.startswith("strategies."):
        module = module.split(".", 1)[1]
    name = getattr(strategy_cls, "__name__", "Strategy")
    return f"{module}.{name}"


def _latest_state_file(path: Path) -> Optional[Path]:
    if not path.exists() or not path.is_dir():
        return None
    candidates = sorted(p for p in path.glob("*.json") if p.is_file())
    return candidates[-1] if candidates else None


def _maybe_load_store_run_summary() -> Optional[Callable[..., Dict[str, Any]]]:
    try:
        from scripts.ev_vs_actual_pnl import store_run_summary
    except ModuleNotFoundError as exc:  # pragma: no cover - optional pandas dependency
        if getattr(exc, "name", "") == "pandas":
            return None
        raise
    return store_run_summary


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
    p.add_argument("--allowed-sessions", default="LDN,NY", help="Comma-separated session codes to allow (e.g., 'LDN,NY'; empty for all)")
    p.add_argument("--k-tp", type=float, default=None, help="Override k_tp (TP in ATR multiples)")
    p.add_argument("--k-sl", type=float, default=None, help="Override k_sl (SL in ATR multiples)")
    p.add_argument("--k-tr", type=float, default=None, help="Override k_tr (trail in ATR multiples)")
    p.add_argument("--or-n", type=int, default=None, help="Override opening-range window n")
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
    p.add_argument("--strategy", default="day_orb_5m.DayORB5m",
                   help="Strategy class to load (module.Class) default=day_orb_5m.DayORB5m")
    p.add_argument("--state-archive", default="ops/state_archive",
                   help="Base directory to archive EV state per strategy/symbol/mode (default: ops/state_archive)")
    p.add_argument("--no-auto-state", action="store_true",
                   help="Disable automatic EV state load/save")
    p.add_argument("--ev-profile", default=None, help="Path to EV profile YAML (default: configs/ev_profiles/<module>.yaml)")
    p.add_argument("--no-ev-profile", action="store_true", help="Disable EV profile seeding")
    p.add_argument("--no-aggregate-ev", action="store_true", help="Skip running aggregate_ev.py after the run")
    p.add_argument("--aggregate-recent", type=int, default=5, help="Recent window size passed to aggregate_ev.py (default 5)")
    p.add_argument("--ev-summary-dir", default=None, help="If set, store EV vs PnL summaries under this directory after each run")
    p.add_argument("--ev-summary-store-daily", action="store_true", help="Persist merged daily CSV when storing EV summary")
    p.add_argument("--ev-summary-top-n", type=int, default=5, help="Number of top positive/negative gap days to keep in stored summary")
    p.add_argument("--ev-auto-optimize", action="store_true", help="Re-estimate EV profile from accumulated records after the run")
    p.add_argument("--ev-optimize-min-trades", type=int, default=5, help="Minimum trades per bucket for EV optimisation")
    p.add_argument("--ev-optimize-alpha-prior", type=float, default=1.0, help="Alpha prior for EV optimisation")
    p.add_argument("--ev-optimize-beta-prior", type=float, default=1.0, help="Beta prior for EV optimisation")
    p.add_argument("--ev-optimize-output-yaml", default=None, help="Where to write updated EV profile YAML (default: overwrite current profile)")
    p.add_argument("--ev-optimize-output-json", default=None, help="Optional JSON dump of optimisation results")
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
    rcfg = build_runner_config(args)
    debug_for_dump = args.debug or bool(args.dump_csv) or bool(args.dump_daily) or bool(args.out_dir)
    from importlib import import_module
    strategy_cls = None
    if args.strategy:
        mod_name, _, cls_name = args.strategy.rpartition('.')
        mod = import_module(f"strategies.{mod_name}") if not mod_name.startswith('strategies.') else import_module(mod_name)
        strategy_cls = getattr(mod, cls_name)
    runner = BacktestRunner(equity=args.equity, symbol=symbol, runner_cfg=rcfg, debug=debug_for_dump, debug_sample_limit=args.dump_max, strategy_cls=strategy_cls)
    strategy_cls = runner.strategy_cls  # ensure default applied when not provided

    ev_profile_path: Optional[str] = None
    if not args.no_ev_profile:
        candidates: List[Path] = []
        if args.ev_profile:
            candidates.append(Path(args.ev_profile))
        module_name = getattr(strategy_cls, "__module__", "").split(".", 1)
        module_tail = module_name[1] if len(module_name) > 1 else module_name[0]
        if module_tail:
            default_profile = Path("configs/ev_profiles") / f"{module_tail}.yaml"
            candidates.append(default_profile)
        for profile_path in candidates:
            if not profile_path:
                continue
            if not profile_path.exists():
                continue
            try:
                with profile_path.open() as f:
                    ev_profile = yaml.safe_load(f)
                if ev_profile:
                    runner.ev_profile = ev_profile
                    runner._apply_ev_profile()
                    ev_profile_path = str(profile_path)
                    break
            except Exception:
                continue

    loaded_state_path: Optional[str] = None
    archive_dir: Optional[Path] = None
    archive_save_path: Optional[str] = None
    if not args.no_auto_state:
        archive_dir = Path(args.state_archive) / _strategy_state_key(strategy_cls) / symbol / args.mode
        latest_state = _latest_state_file(archive_dir)
        if latest_state is not None:
            try:
                runner.load_state_file(str(latest_state))
                loaded_state_path = str(latest_state)
            except Exception:
                loaded_state_path = None
    metrics = runner.run(bars, mode=args.mode)
    out = metrics.as_dict()
    if getattr(metrics, 'debug', None):
        out["debug"] = metrics.debug
    if loaded_state_path:
        out["state_loaded"] = loaded_state_path
    if ev_profile_path:
        out["ev_profile_path"] = ev_profile_path
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
            "allowed_sessions": args.allowed_sessions,
            "or_n": args.or_n,
            "k_tp": args.k_tp,
            "k_sl": args.k_sl,
            "k_tr": args.k_tr,
            "warmup": args.warmup,
            "prior_alpha": args.prior_alpha,
            "prior_beta": args.prior_beta,
            "include_expected_slip": args.include_expected_slip,
            "rv_quantile": args.rv_quantile,
            "calibrate_days": args.calibrate_days,
            "ev_mode": args.ev_mode,
            "size_floor": args.size_floor,
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
            if not args.no_auto_state:
                if archive_dir is None:
                    archive_dir = Path(args.state_archive) / _strategy_state_key(strategy_cls) / symbol / args.mode
                archive_dir.mkdir(parents=True, exist_ok=True)
                stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                archive_name = f"{stamp}_{os.path.basename(run_dir)}.json"
                archive_path = archive_dir / archive_name
                with archive_path.open("w") as f:
                    json.dump(st, f, ensure_ascii=False, indent=2)
                archive_save_path = str(archive_path)
                out["state_archive_path"] = archive_save_path
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
            "or_n": args.or_n,
            "k_tp": args.k_tp,
            "k_sl": args.k_sl,
            "k_tr": args.k_tr,
            "threshold_lcb": args.threshold_lcb,
            "min_or_atr": args.min_or_atr,
            "rv_cuts": args.rv_cuts,
            "allow_low_rv": args.allow_low_rv,
            "allowed_sessions": args.allowed_sessions,
            "warmup": args.warmup,
            "prior_alpha": args.prior_alpha,
            "prior_beta": args.prior_beta,
            "include_expected_slip": args.include_expected_slip,
            "rv_quantile": args.rv_quantile,
            "calibrate_days": args.calibrate_days,
            "ev_mode": args.ev_mode,
            "size_floor": args.size_floor,
            "trades": out.get("trades"),
            "wins": out.get("wins"),
            "total_pips": out.get("total_pips"),
            "sharpe": out.get("sharpe"),
            "max_drawdown": out.get("max_drawdown"),
            "win_rate": (out.get("wins",0)/out.get("trades",1)) if out.get("trades",0) else 0.0,
            "pnl_per_trade": (out.get("total_pips",0.0)/out.get("trades",1)) if out.get("trades",0) else 0.0,
            "gate_block": out.get("debug",{}).get("gate_block"),
            "ev_reject": out.get("debug",{}).get("ev_reject"),
            "ev_bypass": out.get("debug",{}).get("ev_bypass"),
            "dump_rows": out.get("dump_rows"),
            "state_loaded": out.get("state_loaded"),
            "state_archive_path": out.get("state_archive_path"),
            "ev_profile_path": out.get("ev_profile_path"),
        }
        # create or update index CSV (rewrite to ensure column alignment)
        import csv as _csv
        cols = [
            "run_id","run_dir","timestamp","symbol","mode","equity",
            "or_n","k_tp","k_sl","k_tr","threshold_lcb","min_or_atr","rv_cuts","allow_low_rv","allowed_sessions","warmup",
            "prior_alpha","prior_beta","include_expected_slip","rv_quantile","calibrate_days","ev_mode","size_floor",
            "trades","wins","total_pips","sharpe","max_drawdown","win_rate","pnl_per_trade","state_path",
            "gate_block","ev_reject","ev_bypass","dump_rows",
            "state_loaded","state_archive_path","ev_profile_path",
        ]
        existing_rows = []
        if _os.path.exists(index_path):
            with open(index_path, "r", newline="") as f:
                reader = _csv.DictReader(f)
                for r in reader:
                    existing_rows.append(r)
        row["state_path"] = out.get("state_path")
        existing_rows.append(row)
        with open(index_path, "w", newline="") as f:
            w = _csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for r in existing_rows:
                w.writerow({col: r.get(col, "") for col in cols})
        out["index_csv"] = index_path

        ev_summary_status: Optional[Dict[str, Any]] = None
        if args.ev_summary_dir:
            store_summary = _maybe_load_store_run_summary()
            if store_summary is None:
                ev_summary_status = {
                    "store_dir": args.ev_summary_dir,
                    "error": "pandas_not_available",
                }
            else:
                try:
                    summary_output = store_summary(
                        runs_dir=Path(args.out_dir),
                        run_id=id_str,
                        store_dir=Path(args.ev_summary_dir),
                        store_daily=args.ev_summary_store_daily,
                        top_n=max(1, args.ev_summary_top_n),
                    )
                    ev_summary_status = {
                        "store_dir": str(Path(args.ev_summary_dir).expanduser().resolve()),
                        "summary": summary_output.get("summary"),
                        "top_days": summary_output.get("top_days", {}),
                    }
                except Exception as exc:
                    ev_summary_status = {
                        "store_dir": args.ev_summary_dir,
                        "error": str(exc),
                    }
        if ev_summary_status:
            out["ev_summary"] = ev_summary_status
    else:
        if not args.no_auto_state and archive_dir is not None:
            try:
                st = runner.export_state()
                archive_dir.mkdir(parents=True, exist_ok=True)
                stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                archive_path = archive_dir / f"{stamp}.json"
                with archive_path.open("w") as f:
                    json.dump(st, f, ensure_ascii=False, indent=2)
                archive_save_path = str(archive_path)
                out["state_archive_path"] = archive_save_path
            except Exception:
                pass

    if archive_save_path and "state_archive_path" not in out:
        out["state_archive_path"] = archive_save_path

    aggregate_status: Optional[Dict[str, Any]] = None
    if not args.no_aggregate_ev and archive_save_path:
        agg_cmd = [
            sys.executable,
            os.path.join(ROOT, "scripts", "aggregate_ev.py"),
            "--strategy", args.strategy,
            "--symbol", symbol,
            "--mode", args.mode,
            "--archive", str(args.state_archive),
            "--recent", str(max(1, args.aggregate_recent)),
        ]
        if args.ev_profile:
            agg_cmd.extend(["--out-yaml", args.ev_profile])
        agg_cmd.extend(["--out-csv", "analysis/ev_profile_summary.csv"])
        try:
            result = subprocess.run(
                agg_cmd,
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=True,
            )
            aggregate_status = {
                "command": agg_cmd,
                "returncode": result.returncode,
                "stdout": result.stdout.strip() if result.stdout else "",
                "stderr": result.stderr.strip() if result.stderr else "",
            }
        except subprocess.CalledProcessError as exc:
            aggregate_status = {
                "command": agg_cmd,
                "returncode": exc.returncode,
                "error": exc.stderr.strip() if exc.stderr else str(exc),
            }
        except Exception as exc:
            aggregate_status = {
                "command": agg_cmd,
                "returncode": None,
                "error": str(exc),
            }
    if aggregate_status:
        out["aggregate_ev"] = aggregate_status

    ev_optimize_status: Optional[Dict[str, Any]] = None
    if args.ev_auto_optimize:
        if not args.out_dir:
            ev_optimize_status = {
                "error": "ev_auto_optimize requested but --out-dir is not set"
            }
        else:
            opt_cmd = [
                sys.executable,
                os.path.join(ROOT, "scripts", "ev_optimize_from_records.py"),
                "--runs-dir", args.out_dir,
                "--strategy", args.strategy,
                "--symbol", symbol,
                "--mode", args.mode,
                "--min-trades", str(max(1, args.ev_optimize_min_trades)),
                "--alpha-prior", str(args.ev_optimize_alpha_prior),
                "--beta-prior", str(args.ev_optimize_beta_prior),
                "--quiet",
            ]

            # Determine output paths
            if args.ev_optimize_output_json:
                opt_cmd.extend(["--output-json", args.ev_optimize_output_json])

            optimize_yaml_path: Optional[str] = None
            if args.ev_optimize_output_yaml:
                optimize_yaml_path = args.ev_optimize_output_yaml
            elif ev_profile_path:
                optimize_yaml_path = ev_profile_path
            else:
                strategy_module, _, strategy_class = args.strategy.rpartition('.')
                if not strategy_module:
                    strategy_module = args.strategy.lower()
                optimize_yaml_path = os.path.join("configs", "ev_profiles", f"{strategy_module}.yaml")

            if optimize_yaml_path:
                opt_cmd.extend(["--output-yaml", optimize_yaml_path])

            try:
                result = subprocess.run(
                    opt_cmd,
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    check=True,
                )
                ev_optimize_status = {
                    "command": opt_cmd,
                    "returncode": result.returncode,
                    "stdout": result.stdout.strip() if result.stdout else "",
                    "stderr": result.stderr.strip() if result.stderr else "",
                    "output_yaml": optimize_yaml_path,
                    "output_json": args.ev_optimize_output_json,
                }
            except subprocess.CalledProcessError as exc:
                ev_optimize_status = {
                    "command": opt_cmd,
                    "returncode": exc.returncode,
                    "error": exc.stderr.strip() if exc.stderr else str(exc),
                    "output_yaml": optimize_yaml_path,
                    "output_json": args.ev_optimize_output_json,
                }
            except Exception as exc:
                ev_optimize_status = {
                    "command": opt_cmd,
                    "returncode": None,
                    "error": str(exc),
                    "output_yaml": optimize_yaml_path,
                    "output_json": args.ev_optimize_output_json,
                }

    if ev_optimize_status:
        out["ev_optimize"] = ev_optimize_status

    out_json = json.dumps(out)
    if args.json_out:
        with open(args.json_out, "w") as f:
            f.write(out_json)
    else:
        print(out_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
