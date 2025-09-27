#!/usr/bin/env python3
"""Run optimization + evaluation loop until targets satisfied or max iterations reached."""
from __future__ import annotations
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def call(cmd: list[str]) -> subprocess.CompletedProcess:
    print(f"[target_loop] running: {' '.join(cmd)}")
    return subprocess.run(cmd, capture_output=True, text=True)


def run_optuna(trials: int, base_args: list[str], out_path: Path) -> dict | None:
    cmd = [sys.executable, str(ROOT / "scripts/run_optuna_search.py"), "--trials", str(trials), "--out", str(out_path), "--base-args"] + base_args
    result = call(cmd)
    if out_path.exists():
        return json.loads(out_path.read_text(encoding="utf-8"))
    if result.returncode != 0:
        print(result.stderr)
        return None
    try:
        return json.loads(result.stdout.strip()) if result.stdout.strip() else None
    except json.JSONDecodeError:
        return None


def run_sim(base_args: list[str], params: dict, metrics_path: Path, daily_path: Path) -> bool:
    args = [sys.executable, str(ROOT / "scripts/run_sim.py")]
    args += base_args
    args += [
        "--or-n", str(params.get("or_n", 4)),
        "--k-tp", f"{params.get('k_tp', 1.0):.2f}",
        "--k-sl", f"{params.get('k_sl', 0.6):.2f}",
        "--threshold-lcb", f"{params.get('threshold_lcb', 0.3):.2f}",
        "--json-out", str(metrics_path),
        "--dump-daily", str(daily_path),
        "--dump-max", "0",
    ]
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    daily_path.parent.mkdir(parents=True, exist_ok=True)
    result = call(args)
    if result.returncode != 0:
        print(result.stderr)
        return False
    return metrics_path.exists() and daily_path.exists()


def compute_metrics(metrics_json: Path, daily_csv: Path, out_path: Path, equity: float, years: float) -> Path:
    cmd = [sys.executable, str(ROOT / "scripts/compute_metrics.py"),
           "--metrics", str(metrics_json),
           "--daily", str(daily_csv),
           "--equity", str(equity),
           "--years", str(years),
           "--json-out", str(out_path)]
    result = call(cmd)
    if result.returncode != 0:
        print(result.stderr)
    return out_path


def evaluate_targets(metrics_json: Path, targets_json: Path, out_path: Path) -> dict:
    cmd = [sys.executable, str(ROOT / "scripts/evaluate_targets.py"),
           "--metrics", str(metrics_json),
           "--targets", str(targets_json),
           "--json-out", str(out_path)]
    result = call(cmd)
    data = json.loads(out_path.read_text(encoding="utf-8"))
    data["returncode"] = result.returncode
    return data


def get_arg_float(args_list: list[str], key: str, default: float) -> float:
    if key in args_list:
        idx = args_list.index(key)
        if idx + 1 < len(args_list):
            try:
                return float(args_list[idx + 1])
            except ValueError:
                pass
    return default


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Optimize until targets achieved")
    p.add_argument("--trials", type=int, default=5)
    p.add_argument("--max-iter", type=int, default=5)
    p.add_argument("--targets", default="configs/targets.json")
    p.add_argument("--base-args", nargs=argparse.REMAINDER,
                   default=["--csv", "data/usdjpy_5m_2018-2024_utc.csv",
                            "--symbol", "USDJPY",
                            "--mode", "conservative",
                            "--equity", "100000",
                            "--allow-low-rv",
                            "--allowed-sessions", "LDN,NY"],
                   help="Base arguments for run_sim")
    p.add_argument("--out", default="analysis/target_loop_summary.json")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    out_records = []
    for i in range(1, args.max_iter + 1):
        optuna_out = Path(f"analysis/optuna_iter{i}.json")
        best = run_optuna(args.trials, args.base_args, optuna_out)
        if not best:
            out_records.append({"iteration": i, "status": "optuna_failed"})
            continue
        metrics_path = Path(f"reports/iter{i}_metrics.json")
        daily_path = Path(f"reports/iter{i}_daily.csv")
        if not run_sim(args.base_args, best.get("best_params", {}), metrics_path, daily_path):
            out_records.append({"iteration": i, "status": "sim_failed"})
            continue
        agg_path = Path(f"reports/iter{i}_agg.json")
        equity = get_arg_float(args.base_args, "--equity", 100000.0)
        compute_metrics(metrics_path, daily_path, agg_path, equity=equity, years=6.0)
        eval_path = Path(f"reports/iter{i}_eval.json")
        result = evaluate_targets(agg_path, Path(args.targets), eval_path)
        out_records.append({"iteration": i, "optuna": best, "metrics": json.loads(agg_path.read_text()), "evaluation": result})
        if result.get("passed"):
            break
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out_records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out_records, ensure_ascii=False, indent=2))
    return 0 if out_records and out_records[-1].get("evaluation", {}).get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
