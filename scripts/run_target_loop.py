#!/usr/bin/env python3
"""Run optimization + evaluation loop until targets satisfied or max iterations reached."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.utils import yaml_compat as yaml


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


def _resolve_repo_path(path: Path) -> Path:
    if path.is_absolute():
        return path
    return (ROOT / path).resolve()


def _load_manifest(path: Path) -> Dict[str, Any]:
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise FileNotFoundError(f"manifest not found: {path}")
    data = yaml.safe_load(content)
    if not isinstance(data, dict):
        raise ValueError("manifest must be a mapping")
    return data


def _apply_params_to_manifest(data: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    manifest = json.loads(json.dumps(data))
    strategy_block = manifest.setdefault("strategy", {})
    parameters = strategy_block.setdefault("parameters", {})
    runner_block = manifest.setdefault("runner", {})
    runner_cfg = runner_block.setdefault("runner_config", {})
    runner_cli = runner_block.setdefault("cli_args", {})

    if "or_n" in params:
        try:
            parameters["or_n"] = int(params["or_n"])
        except (TypeError, ValueError):
            pass
    if "k_tp" in params:
        try:
            parameters["k_tp"] = float(params["k_tp"])
        except (TypeError, ValueError):
            pass
    if "k_sl" in params:
        try:
            parameters["k_sl"] = float(params["k_sl"])
        except (TypeError, ValueError):
            pass
    if "threshold_lcb" in params:
        try:
            value = float(params["threshold_lcb"])
        except (TypeError, ValueError):
            value = None
        if value is not None:
            runner_cfg["threshold_lcb_pip"] = value
            runner_cli["threshold_lcb"] = value

    return manifest


def _build_run_sim_args(
    base_args: List[str],
    manifest_path: Path,
    metrics_path: Path,
    daily_path: Path,
) -> List[str]:
    passthrough: List[str] = []
    skip_next = False
    for token in base_args:
        if skip_next:
            skip_next = False
            continue
        if token == "--manifest":
            skip_next = True
            continue
        if token in {"--json-out", "--out-json", "--dump-daily", "--out-daily-csv"}:
            skip_next = True
            continue
        passthrough.append(token)
    cmd = [sys.executable, str(ROOT / "scripts/run_sim.py"), "--manifest", str(manifest_path)]
    cmd.extend(passthrough)
    cmd.extend(["--json-out", str(metrics_path), "--out-daily-csv", str(daily_path)])
    return cmd


def run_sim(base_args: list[str], params: dict, metrics_path: Path, daily_path: Path) -> bool:
    manifest_arg: Path | None = None
    tokens = list(base_args)
    for idx, token in enumerate(tokens):
        if token == "--manifest" and idx + 1 < len(tokens):
            manifest_arg = _resolve_repo_path(Path(tokens[idx + 1]))
            break
    if manifest_arg is None:
        print("[target_loop] --manifest must be supplied via --base-args")
        return False

    try:
        manifest_data = _load_manifest(manifest_arg)
    except Exception as exc:  # noqa: BLE001
        print(f"[target_loop] failed to load manifest {manifest_arg}: {exc}")
        return False

    manifest_with_params = _apply_params_to_manifest(manifest_data, params or {})

    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    daily_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="target_loop_") as tmp_dir:
        tmp_manifest_path = Path(tmp_dir) / "manifest.yaml"
        with tmp_manifest_path.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(manifest_with_params, handle, sort_keys=False)
        cmd = _build_run_sim_args(tokens, tmp_manifest_path, metrics_path, daily_path)
        result = call(cmd)

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
    p.add_argument(
        "--base-args",
        nargs=argparse.REMAINDER,
        default=[
            "--manifest",
            "configs/strategies/day_orb_5m.yaml",
            "--csv",
            "validated/USDJPY/5m.csv",
            "--symbol",
            "USDJPY",
            "--mode",
            "conservative",
            "--equity",
            "100000",
        ],
        help="Base arguments for run_sim",
    )
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
