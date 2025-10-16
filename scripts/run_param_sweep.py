#!/usr/bin/env python3
"""Run parameter sweeps for Day ORB experiments."""
from __future__ import annotations

import argparse
import copy
import json
import random
import shlex
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

try:
    import pandas as pd
except ModuleNotFoundError:  # pragma: no cover - optional dependency guard
    pd = None  # type: ignore

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.utils import yaml_compat as yaml  # noqa: E402
from experiments.history.utils import compute_dataset_fingerprint  # noqa: E402
from scripts._param_sweep import (  # noqa: E402
    ExperimentConfig,
    evaluate_constraints,
    load_experiment_config,
)
from scripts._time_utils import utcnow_aware, utcnow_iso  # noqa: E402


@dataclass
class TrialSpec:
    index: int
    params: Dict[str, Any]
    seed: int
    token: str


@dataclass
class TrialResult:
    spec: TrialSpec
    status: str
    result_path: Path


def _require_pandas() -> None:
    if pd is None:
        raise RuntimeError("pandas is required for sweep metric evaluation")


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", required=True, help="Experiment config name or path")
    parser.add_argument(
        "--search",
        choices=("grid", "random", "bayes"),
        default="grid",
        help="Search strategy to use",
    )
    parser.add_argument("--max-trials", type=int, default=0, help="Maximum number of trials to run")
    parser.add_argument("--workers", type=int, default=1, help="Number of parallel workers")
    parser.add_argument("--out", help="Override output directory for trial artefacts")
    parser.add_argument("--seed", type=int, help="Random seed for sampling order")
    parser.add_argument("--log-history", action="store_true", help="Log runs to experiments/history")
    parser.add_argument("--dry-run", action="store_true", help="Plan trials without executing run_sim")
    return parser.parse_args(argv)


def _shlex_join(parts: Sequence[str]) -> str:
    try:
        return shlex.join(parts)
    except AttributeError:  # pragma: no cover - Python <3.8 fallback
        return " ".join(shlex.quote(part) for part in parts)


def _build_trial_token(timestamp: str, seed: int) -> str:
    return f"{timestamp}_{seed:08x}"


def _discover_run_dir(trial_dir: Path) -> Optional[Path]:
    candidates = [entry for entry in trial_dir.iterdir() if entry.is_dir()]
    if not candidates:
        return None
    candidates.sort(key=lambda item: item.stat().st_mtime)
    return candidates[-1]


def _relative_path(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _compute_trades_per_month(daily: pd.DataFrame) -> float:
    _require_pandas()
    if daily.empty:
        return 0.0
    if "date" not in daily.columns:
        return 0.0
    fills = daily.get("fills")
    try:
        fills = fills.astype(float)
    except ValueError:
        fills = pd.to_numeric(fills, errors="coerce")
    periods = pd.to_datetime(daily["date"], errors="coerce").dt.to_period("M")
    grouped = pd.DataFrame({"fills": fills, "period": periods}).dropna()
    if grouped.empty:
        return 0.0
    trades_by_month = grouped.groupby("period")["fills"].sum()
    if trades_by_month.empty:
        return 0.0
    return float(trades_by_month.sum() / len(trades_by_month))


def _max_drawdown(series: pd.Series) -> float:
    if series.empty:
        return 0.0
    cumulative = series.cumsum()
    peak = cumulative.cummax()
    drawdown = cumulative - peak
    return float(drawdown.min())


def _profit_factor(trades: pd.Series) -> float:
    gains = trades[trades > 0].sum()
    losses = trades[trades < 0].sum()
    if losses == 0 or gains == 0:
        return 0.0
    return float(gains / abs(losses))


def _compute_summary(
    metrics: Dict[str, Any],
    daily: pd.DataFrame,
    *,
    equity: Optional[float],
    years_from_data: bool,
) -> Dict[str, Any]:
    _require_pandas()
    summary: Dict[str, Any] = {}
    trades = int(metrics.get("trades", 0) or 0)
    wins = int(metrics.get("wins", 0) or 0)
    total_pips = float(metrics.get("total_pips", 0.0) or 0.0)
    daily_pnl = pd.to_numeric(daily.get("pnl_pips"), errors="coerce").fillna(0.0)
    pnl_std = float(daily_pnl.std(ddof=0))
    sharpe = float(daily_pnl.mean() / pnl_std) if pnl_std else 0.0
    summary.update(
        {
            "trades": trades,
            "wins": wins,
            "losses": max(trades - wins, 0),
            "total_pips": total_pips,
            "win_rate": (wins / trades) if trades else 0.0,
            "pips_per_trade": (total_pips / trades) if trades else 0.0,
            "sharpe": sharpe,
            "max_drawdown": _max_drawdown(daily_pnl),
            "profit_factor": _profit_factor(daily_pnl),
            "trades_per_month": _compute_trades_per_month(daily),
        }
    )
    if equity:
        duration_years = None
        if years_from_data and not daily.empty:
            start = pd.to_datetime(daily["date"], errors="coerce").dropna()
            if not start.empty:
                total_days = (start.max() - start.min()).days or 1
                duration_years = max(total_days / 365.25, 1 / 12)
        if duration_years is None:
            duration_years = 1.0
        final_equity = equity + total_pips
        if final_equity > 0 and equity > 0:
            summary["cagr"] = (final_equity / equity) ** (1 / duration_years) - 1
        else:
            summary["cagr"] = -1.0
        summary["equity"] = equity
    return summary


def _compute_seasonal_metrics(
    daily: pd.DataFrame,
    slices,
    *,
    equity: Optional[float],
    years_from_data: bool,
) -> Dict[str, Dict[str, Any]]:
    _require_pandas()
    results: Dict[str, Dict[str, Any]] = {}
    if daily.empty:
        return results
    daily_dates = pd.to_datetime(daily.get("date"), errors="coerce")
    for slice_cfg in slices:
        mask = (daily_dates >= pd.Timestamp(slice_cfg.start)) & (daily_dates <= pd.Timestamp(slice_cfg.end))
        if mask.any():
            slice_frame = daily.loc[mask].copy()
        else:
            slice_frame = pd.DataFrame(columns=daily.columns)
        metrics = {
            "trades": float(slice_frame.get("fills", pd.Series(dtype=float)).sum()),
            "wins": float(slice_frame.get("wins", pd.Series(dtype=float)).sum()),
            "total_pips": float(slice_frame.get("pnl_pips", pd.Series(dtype=float)).sum()),
        }
        summary = _compute_summary(metrics, slice_frame, equity=equity, years_from_data=years_from_data)
        results[slice_cfg.id] = summary
    return results


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class SweepRunner:
    def __init__(
        self,
        config: ExperimentConfig,
        args: argparse.Namespace,
        *,
        timestamp: str,
    ) -> None:
        self.config = config
        self.args = args
        self.timestamp = timestamp
        manifest_text = config.manifest_path.read_text(encoding="utf-8")
        self.base_manifest_data = yaml.safe_load(manifest_text)
        self.commit_sha: Optional[str] = None
        self.repo_root = ROOT
        self.dataset_path = self._discover_dataset_path()
        self.dataset_fingerprint = self._compute_dataset_fingerprint()

    def _apply_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        manifest_data = copy.deepcopy(self.base_manifest_data)
        for name, value in params.items():
            dimension = self.config.dimension_map.get(name)
            if not dimension:
                continue
            target = manifest_data
            for token in dimension.path[:-1]:
                target = target.setdefault(token, {})
                if not isinstance(target, dict):
                    raise ValueError(f"Path {'/'.join(dimension.path)} collides with non-mapping in manifest")
            target[dimension.path[-1]] = value
        return manifest_data

    def _build_command(self, manifest_path: Path, trial_dir: Path) -> List[str]:
        cmd = [sys.executable, str(ROOT / "scripts" / "run_sim.py"), "--manifest", str(manifest_path)]
        cmd.extend(self.config.runner_cli)
        if "--out-dir" not in self.config.runner_cli:
            cmd.extend(["--out-dir", str(trial_dir)])
        return cmd

    def _ensure_commit_sha(self) -> str:
        if self.commit_sha:
            return self.commit_sha
        result = subprocess.run([
            "git",
            "rev-parse",
            "HEAD",
        ], cwd=self.repo_root, check=True, capture_output=True, text=True)
        self.commit_sha = result.stdout.strip()
        return self.commit_sha

    def _discover_dataset_path(self) -> Optional[Path]:
        tokens = list(self.config.runner_cli)
        for index, token in enumerate(tokens):
            if token == "--csv" and index + 1 < len(tokens):
                candidate = Path(tokens[index + 1])
                if not candidate.is_absolute():
                    candidate = (ROOT / candidate).resolve()
                return candidate
        return None

    def _compute_dataset_fingerprint(self) -> Optional[Dict[str, Any]]:
        if not self.dataset_path:
            return None
        try:
            sha_value, rows = compute_dataset_fingerprint(self.dataset_path)
        except FileNotFoundError:
            return {
                "path": _relative_path(self.dataset_path),
                "sha256": None,
                "rows": None,
            }
        return {
            "path": _relative_path(self.dataset_path),
            "sha256": sha_value,
            "rows": rows,
        }

    def _log_history(self, run_dir: Path, command: str) -> Dict[str, Any]:
        details: Dict[str, Any] = {"logged": False}
        if not self.args.log_history or not self.config.history_enabled:
            return details
        try:
            cmd = [
                sys.executable,
                str(ROOT / "scripts" / "log_experiment.py"),
                "--run-dir",
                str(run_dir),
                "--manifest-id",
                self.config.manifest_id or self.config.identifier,
                "--mode",
                self.config.mode or "conservative",
                "--commit-sha",
                self._ensure_commit_sha(),
                "--command",
                command,
            ]
            subprocess.run(cmd, check=True, cwd=self.repo_root)
            details.update({"logged": True, "command": cmd})
        except subprocess.CalledProcessError as exc:  # pragma: no cover - defensive safeguard
            details.update({"logged": False, "error": str(exc)})
        return details

    def _run_single(self, spec: TrialSpec, trial_dir: Path) -> TrialResult:
        result_path = trial_dir / "result.json"
        params_path = trial_dir / "params.json"
        manifest_override = trial_dir / "manifest.yaml"
        stdout_path = trial_dir / "stdout.log"
        stderr_path = trial_dir / "stderr.log"
        trial_dir.mkdir(parents=True, exist_ok=True)
        if pd is None and not self.args.dry_run:
            raise RuntimeError("pandas is required to evaluate sweep metrics")
        manifest_data = self._apply_params(spec.params)
        manifest_override.write_text(yaml.safe_dump(manifest_data, sort_keys=False), encoding="utf-8")
        _write_json(params_path, spec.params)
        command = self._build_command(manifest_override, trial_dir)
        command_str = _shlex_join(command)
        start_time = utcnow_aware()
        metadata: Dict[str, Any] = {
            "trial_id": spec.token,
            "params": spec.params,
            "seed": spec.seed,
            "search": self.args.search,
            "command": command,
            "command_str": command_str,
            "start_time": start_time.isoformat(),
            "timestamp": self.timestamp,
            "status": "planned",
        }
        if self.dataset_fingerprint:
            metadata["dataset"] = self.dataset_fingerprint
        if self.args.dry_run:
            metadata.update({"status": "dry_run", "duration_seconds": 0.0})
            _write_json(result_path, metadata)
            return TrialResult(spec=spec, status="dry_run", result_path=result_path)
        process = subprocess.run(
            command,
            cwd=self.repo_root,
            capture_output=True,
            text=True,
        )
        stdout_path.write_text(process.stdout or "", encoding="utf-8")
        stderr_path.write_text(process.stderr or "", encoding="utf-8")
        end_time = utcnow_aware()
        metadata.update(
            {
                "stdout": _relative_path(stdout_path),
                "stderr": _relative_path(stderr_path),
                "returncode": process.returncode,
                "end_time": end_time.isoformat(),
                "duration_seconds": (end_time - start_time).total_seconds(),
            }
        )
        if process.returncode != 0:
            metadata.update({"status": "failed"})
            _write_json(result_path, metadata)
            return TrialResult(spec=spec, status="failed", result_path=result_path)
        run_dir = _discover_run_dir(trial_dir)
        if not run_dir:
            metadata.update({"status": "error", "error": "run directory not created"})
            _write_json(result_path, metadata)
            return TrialResult(spec=spec, status="error", result_path=result_path)
        metrics_path = run_dir / "metrics.json"
        daily_path = run_dir / "daily.csv"
        try:
            metrics_data = json.loads(metrics_path.read_text(encoding="utf-8"))
            daily_frame = pd.read_csv(daily_path)
        except FileNotFoundError:
            metadata.update({"status": "error", "error": "missing metrics or daily outputs"})
            _write_json(result_path, metadata)
            return TrialResult(spec=spec, status="error", result_path=result_path)
        summary = _compute_summary(
            metrics_data,
            daily_frame,
            equity=self.config.runner_equity,
            years_from_data=self.config.use_years_from_data,
        )
        seasonal = _compute_seasonal_metrics(
            daily_frame,
            self.config.seasonal_slices,
            equity=self.config.runner_equity,
            years_from_data=self.config.use_years_from_data,
        )
        context = self.config.make_context(params=spec.params, metrics=summary, seasonal=seasonal)
        constraints, feasible = evaluate_constraints(context, self.config.constraints)
        score, breakdown = self.config.scoring.compute(context)
        metadata.update(
            {
                "status": "completed",
                "run_dir": _relative_path(run_dir),
                "metrics_path": _relative_path(metrics_path),
                "metrics": summary,
                "seasonal": seasonal,
                "constraints": constraints,
                "feasible": feasible,
                "score": score,
                "score_breakdown": breakdown,
                "tie_breakers": self.config.scoring.tie_breaker_values(context),
            }
        )
        history_info = self._log_history(run_dir, command_str)
        if history_info:
            metadata["history"] = history_info
        _write_json(result_path, metadata)
        return TrialResult(spec=spec, status="completed", result_path=result_path)

    def run_trials(self, plans: Sequence[TrialSpec], out_dir: Path) -> List[TrialResult]:
        results: List[TrialResult] = []
        if self.args.workers <= 1:
            for spec in plans:
                trial_dir = out_dir / spec.token
                results.append(self._run_single(spec, trial_dir))
            return results
        with ThreadPoolExecutor(max_workers=self.args.workers) as executor:
            future_map = {
                executor.submit(self._run_single, spec, out_dir / spec.token): spec for spec in plans
            }
            for future in as_completed(future_map):
                results.append(future.result())
        return results


def _prepare_trials(config: ExperimentConfig, args: argparse.Namespace, timestamp: str) -> List[TrialSpec]:
    plans: List[TrialSpec] = []
    space_size = config.search_space_size()
    limit = args.max_trials if args.max_trials and args.max_trials > 0 else space_size
    if args.search == "bayes":
        raise NotImplementedError("Bayesian optimisation integration is pending implementation")
    if args.search == "grid":
        if not config.dimensions:
            limit = 0
        count = 0
        for combination in _iter_grid(config.dimensions):
            if limit and count >= limit:
                break
            seed = count
            plans.append(
                TrialSpec(
                    index=count,
                    params=combination,
                    seed=seed,
                    token=_build_trial_token(timestamp, seed),
                )
            )
            count += 1
        return plans
    max_trials = limit if limit else space_size
    if max_trials <= 0:
        return plans
    master_seed = args.seed if args.seed is not None else int(time.time())
    rng = random.Random(master_seed)
    seen: set[tuple[tuple[str, Any], ...]] = set()
    attempts = 0
    max_attempts = max_trials * 5
    while len(plans) < max_trials and attempts < max_attempts:
        attempts += 1
        seed = rng.randrange(1, 2**32 - 1)
        trial_rng = random.Random(seed)
        params = {dim.name: dim.sample(trial_rng) for dim in config.dimensions}
        key = tuple((name, params[name]) for name in sorted(params))
        if key in seen:
            continue
        seen.add(key)
        plans.append(
            TrialSpec(
                index=len(plans),
                params=params,
                seed=seed,
                token=_build_trial_token(timestamp, seed),
            )
        )
    return plans


def _iter_grid(dimensions: Sequence) -> Iterable[Dict[str, Any]]:
    if not dimensions:
        yield {}
        return
    from itertools import product

    keys = [dim.name for dim in dimensions]
    value_lists = [dim.discrete_values() for dim in dimensions]
    for combo in product(*value_lists):
        yield {key: value for key, value in zip(keys, combo)}


def _build_log_entry(result_path: Path) -> Optional[Dict[str, Any]]:
    if not result_path.exists():
        return None
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:  # pragma: no cover - defensive guard
        return None
    status = str(payload.get("status", "unknown"))
    constraints = payload.get("constraints") or {}
    failed = [cid for cid, entry in constraints.items() if (entry or {}).get("status") == "fail"]
    feasible_value = payload.get("feasible")
    if status == "completed":
        if isinstance(feasible_value, bool):
            feasible = feasible_value
        else:
            feasible = not failed
    else:
        feasible = bool(feasible_value)
    entry = {
        "trial_id": payload.get("trial_id"),
        "status": status,
        "feasible": feasible,
        "constraints": constraints,
        "failed_constraints": failed,
        "score": payload.get("score"),
        "result_path": _relative_path(result_path),
        "run_dir": payload.get("run_dir"),
        "metrics_path": payload.get("metrics_path"),
    }
    dataset = payload.get("dataset")
    if dataset:
        entry["dataset"] = dataset
    return entry


def _write_sweep_log(config: ExperimentConfig, output_dir: Path) -> None:
    entries: List[Dict[str, Any]] = []
    if not output_dir.exists():
        return
    for trial_dir in sorted([item for item in output_dir.iterdir() if item.is_dir()], key=lambda item: item.name):
        result_path = trial_dir / "result.json"
        entry = _build_log_entry(result_path)
        if entry:
            entries.append(entry)
    summary = {
        "total": len(entries),
        "completed": sum(1 for item in entries if item.get("status") == "completed"),
        "success": sum(
            1
            for item in entries
            if item.get("status") == "completed" and bool(item.get("feasible"))
        ),
        "violations": sum(
            1
            for item in entries
            if item.get("status") == "completed" and not bool(item.get("feasible"))
        ),
        "dry_run": sum(1 for item in entries if item.get("status") == "dry_run"),
    }
    payload = {
        "experiment": config.identifier,
        "config_path": _relative_path(config.path),
        "generated_at": utcnow_iso(),
        "entries": entries,
        "summary": summary,
    }
    _write_json(output_dir / "log.json", payload)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)
    config = load_experiment_config(args.experiment)
    output_dir = Path(args.out).resolve() if args.out else config.base_output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = utcnow_aware().strftime("%Y%m%d_%H%M%S")
    try:
        plans = _prepare_trials(config, args, timestamp)
    except NotImplementedError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    runner = SweepRunner(config, args, timestamp=timestamp)
    results = runner.run_trials(plans, output_dir)
    completed = sum(1 for item in results if item.status == "completed")
    failures = sum(1 for item in results if item.status not in {"completed", "dry_run"})
    summary = {
        "experiment": config.identifier,
        "config_path": _relative_path(config.path),
        "timestamp": utcnow_iso(),
        "search": args.search,
        "total_trials": len(plans),
        "completed": completed,
        "failures": failures,
        "dry_run": args.dry_run,
    }
    _write_json(output_dir / "sweep_summary.json", summary)
    _write_sweep_log(config, output_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if failures == 0 else 1


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())
