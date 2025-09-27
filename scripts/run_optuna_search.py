#!/usr/bin/env python3
"""Run Optuna-based hyperparameter search."""
from __future__ import annotations
import argparse
import json
import optuna
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_sim(args_list):
    cmd = [sys.executable, str(ROOT / "scripts/run_sim.py")] + args_list
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout.strip())
    except json.JSONDecodeError:
        return None


def objective(trial, base_args):
    or_n = trial.suggest_int("or_n", 4, 8)
    k_tp = trial.suggest_float("k_tp", 0.8, 1.2)
    k_sl = trial.suggest_float("k_sl", 0.4, 0.8)
    threshold = trial.suggest_float("threshold_lcb", 0.0, 0.5)

    run_args = base_args + [
        "--or-n", str(or_n),
        "--k-tp", f"{k_tp:.2f}",
        "--k-sl", f"{k_sl:.2f}",
        "--threshold-lcb", f"{threshold:.2f}",
    ]
    metrics = run_sim(run_args)
    if not metrics:
        return float("inf")
    total_pips = metrics.get("total_pips", 0.0)
    # minimize negative total pips -> maximize total_pips
    return -total_pips


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Optuna hyperparameter search")
    p.add_argument("--trials", type=int, default=10)
    p.add_argument("--out", default="analysis/optuna_best.json")
    p.add_argument("--base-args", nargs=argparse.REMAINDER,
                   default=["--csv", "data/usdjpy_5m_2018-2024_utc.csv",
                            "--symbol", "USDJPY",
                            "--mode", "conservative",
                            "--equity", "100000"],
                   help="base args for run_sim")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    study = optuna.create_study(direction="minimize")
    study.optimize(lambda t: objective(t, args.base_args), n_trials=args.trials)
    Path(args.out).write_text(json.dumps({"best_params": study.best_params, "best_value": study.best_value}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"best_params": study.best_params, "best_value": study.best_value}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
