#!/usr/bin/env python3
"""runs/index.csv を params.json + metrics.json から再構築する小スクリプト"""
from __future__ import annotations
import argparse
import csv
import json
from pathlib import Path
from typing import List, Dict, Any

DEFAULT_COLUMNS = [
    "run_id",
    "run_dir",
    "manifest_id",
    "timestamp",
    "symbol",
    "mode",
    "equity",
    "or_n",
    "k_tp",
    "k_sl",
    "k_tr",
    "threshold_lcb",
    "min_or_atr",
    "rv_cuts",
    "allow_low_rv",
    "allowed_sessions",
    "warmup",
    "prior_alpha",
    "prior_beta",
    "include_expected_slip",
    "rv_quantile",
    "calibrate_days",
    "ev_mode",
    "size_floor",
    "trades",
    "wins",
    "total_pips",
    "sharpe",
    "max_drawdown",
    "win_rate",
    "pnl_per_trade",
    "state_path",
    "gate_block",
    "ev_reject",
    "ev_bypass",
    "dump_rows",
    "state_loaded",
    "state_archive_path",
    "ev_profile_path",
]


def extract_timestamp(run_id: str) -> str:
    parts = run_id.split("_")
    if len(parts) >= 2:
        date_part, time_part = parts[-2], parts[-1]
        if len(date_part) == 8 and date_part.isdigit() and len(time_part) == 6 and time_part.isdigit():
            return f"{date_part}_{time_part}"
    return ""


def load_json(path: Path) -> Dict[str, Any]:
    with path.open() as f:
        return json.load(f)


def _as_float(value: Any) -> float:
    try:
        if value is None:
            raise TypeError
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _coerce_debug(metrics: Dict[str, Any]) -> Dict[str, Any]:
    debug = metrics.get("debug", {})
    return debug if isinstance(debug, dict) else {}


def gather_rows(runs_dir: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for run_dir in sorted(runs_dir.iterdir()):
        if not run_dir.is_dir():
            continue
        params_path = run_dir / "params.json"
        metrics_path = run_dir / "metrics.json"
        if not params_path.exists() or not metrics_path.exists():
            continue
        try:
            params = load_json(params_path)
            metrics = load_json(metrics_path)
        except Exception:
            continue
        row: Dict[str, Any] = {}
        run_id = run_dir.name
        row["run_id"] = run_id
        row["run_dir"] = str(run_dir)
        manifest_id = metrics.get("manifest_id")
        if manifest_id is None:
            manifest_id = ""
        else:
            manifest_id = str(manifest_id)
        row["manifest_id"] = manifest_id
        row["timestamp"] = extract_timestamp(run_id)
        row["symbol"] = params.get("symbol")
        row["mode"] = params.get("mode")
        row["equity"] = params.get("equity")
        row["or_n"] = params.get("or_n")
        row["k_tp"] = params.get("k_tp")
        row["k_sl"] = params.get("k_sl")
        row["k_tr"] = params.get("k_tr")
        row["threshold_lcb"] = params.get("threshold_lcb")
        row["min_or_atr"] = params.get("min_or_atr")
        row["rv_cuts"] = params.get("rv_cuts")
        row["allow_low_rv"] = params.get("allow_low_rv")
        row["allowed_sessions"] = params.get("allowed_sessions")
        row["warmup"] = params.get("warmup")
        row["prior_alpha"] = params.get("prior_alpha")
        row["prior_beta"] = params.get("prior_beta")
        row["include_expected_slip"] = params.get("include_expected_slip")
        row["rv_quantile"] = params.get("rv_quantile")
        row["calibrate_days"] = params.get("calibrate_days")
        row["ev_mode"] = params.get("ev_mode")
        row["size_floor"] = params.get("size_floor")
        row["trades"] = metrics.get("trades")
        row["wins"] = metrics.get("wins")
        row["total_pips"] = metrics.get("total_pips")
        row["sharpe"] = metrics.get("sharpe")
        row["max_drawdown"] = metrics.get("max_drawdown")
        trades_f = _as_float(metrics.get("trades"))
        wins_f = _as_float(metrics.get("wins"))
        total_pips_f = _as_float(metrics.get("total_pips"))
        row["win_rate"] = wins_f / trades_f if trades_f else 0.0
        row["pnl_per_trade"] = total_pips_f / trades_f if trades_f else 0.0
        debug = _coerce_debug(metrics)
        gate_block = metrics.get("gate_block")
        if gate_block is None:
            gate_block = debug.get("gate_block")
        row["gate_block"] = gate_block
        ev_reject = metrics.get("ev_reject")
        if ev_reject is None:
            ev_reject = debug.get("ev_reject")
        row["ev_reject"] = ev_reject
        ev_bypass = metrics.get("ev_bypass")
        if ev_bypass is None:
            ev_bypass = debug.get("ev_bypass")
        row["ev_bypass"] = ev_bypass
        row["dump_rows"] = metrics.get("dump_rows")
        row["state_loaded"] = metrics.get("state_loaded")
        row["state_archive_path"] = metrics.get("state_archive_path")
        row["ev_profile_path"] = metrics.get("ev_profile_path")
        state_path = metrics.get("state_path")
        if state_path:
            row["state_path"] = state_path
        else:
            state_file = run_dir / "state.json"
            row["state_path"] = str(state_file) if state_file.exists() else ""
        rows.append(row)
    rows.sort(key=lambda r: r.get("timestamp", ""))
    return rows


def write_index(rows: List[Dict[str, Any]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=DEFAULT_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in DEFAULT_COLUMNS})


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild runs/index.csv")
    parser.add_argument("--runs-dir", default="runs", help="集計対象のディレクトリ")
    parser.add_argument("--out", default="runs/index.csv", help="出力先のCSV")
    args = parser.parse_args()

    runs_dir = Path(args.runs_dir)
    if not runs_dir.exists():
        raise SystemExit(f"runs dir not found: {runs_dir}")

    rows = gather_rows(runs_dir)
    write_index(rows, Path(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
