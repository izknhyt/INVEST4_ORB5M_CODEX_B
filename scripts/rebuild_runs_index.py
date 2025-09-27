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
    "timestamp",
    "symbol",
    "mode",
    "equity",
    "or_n",
    "k_tp",
    "k_sl",
    "threshold_lcb",
    "min_or_atr",
    "rv_cuts",
    "allow_low_rv",
    "allowed_sessions",
    "warmup",
    "trades",
    "wins",
    "total_pips",
    "state_path",
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
        row["timestamp"] = extract_timestamp(run_id)
        row["symbol"] = params.get("symbol")
        row["mode"] = params.get("mode")
        row["equity"] = params.get("equity")
        row["or_n"] = params.get("or_n")
        row["k_tp"] = params.get("k_tp")
        row["k_sl"] = params.get("k_sl")
        row["threshold_lcb"] = params.get("threshold_lcb")
        row["min_or_atr"] = params.get("min_or_atr")
        row["rv_cuts"] = params.get("rv_cuts")
        row["allow_low_rv"] = params.get("allow_low_rv")
        row["allowed_sessions"] = params.get("allowed_sessions")
        row["warmup"] = params.get("warmup")
        row["trades"] = metrics.get("trades")
        row["wins"] = metrics.get("wins")
        row["total_pips"] = metrics.get("total_pips")
        row["state_loaded"] = metrics.get("state_loaded")
        row["state_archive_path"] = metrics.get("state_archive_path")
        row["ev_profile_path"] = metrics.get("ev_profile_path")
        state_path = run_dir / "state.json"
        row["state_path"] = str(state_path) if state_path.exists() else ""
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
