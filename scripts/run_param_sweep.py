#!/usr/bin/env python3
"""Run parameter sweeps for Day ORB experiments."""
from __future__ import annotations

import argparse
import copy
import json
import math
import random
import shlex
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

try:
    import pandas as pd
except ModuleNotFoundError:  # pragma: no cover - optional dependency guard
    pd = None  # type: ignore

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from configs.strategies.loader import load_manifest  # noqa: E402
from core.router_pipeline import PortfolioTelemetry, build_portfolio_state  # noqa: E402
from core.utils import yaml_compat as yaml  # noqa: E402
from experiments.history.utils import compute_dataset_fingerprint  # noqa: E402
from scripts._param_sweep import (  # noqa: E402
    BayesConfig,
    ExperimentConfig,
    PortfolioConfig,
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
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TrialResult:
    spec: TrialSpec
    status: str
    result_path: Path
    payload: Optional[Dict[str, Any]] = None


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
    parser.add_argument(
        "--portfolio-config",
        help="Optional portfolio configuration override (YAML file or inline mapping)",
    )
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


def _normalise_equity_curve(curve_raw: Any) -> List[Tuple[str, float]]:
    result: List[Tuple[str, float]] = []
    if not isinstance(curve_raw, Sequence):
        return result
    for entry in curve_raw:
        timestamp: Optional[str]
        equity_value: Optional[float]
        if isinstance(entry, Mapping):
            timestamp = entry.get("timestamp") or entry.get("time") or entry.get("ts")
            equity_raw = entry.get("equity") or entry.get("value")
        elif isinstance(entry, Sequence) and len(entry) >= 2:
            timestamp = entry[0]
            equity_raw = entry[1]
        else:
            continue
        if timestamp is None:
            continue
        try:
            equity_value = float(equity_raw)
        except (TypeError, ValueError):
            continue
        result.append((str(timestamp), equity_value))
    result.sort(key=lambda item: item[0])
    return result


def _curve_returns(curve: Sequence[Tuple[str, float]]) -> Tuple[List[float], float]:
    if not curve:
        return [], 0.0
    base_equity = float(curve[0][1]) if curve else 0.0
    returns: List[float] = []
    if base_equity == 0:
        base_equity = 1.0
    previous = curve[0][1]
    for _, equity in curve[1:]:
        try:
            next_equity = float(equity)
        except (TypeError, ValueError):
            continue
        returns.append((next_equity - previous) / base_equity)
        previous = next_equity
    return returns, float(curve[0][1]) if curve else 0.0


def _combine_returns(
    returns_map: Mapping[str, Sequence[float]], positions: Mapping[str, float]
) -> List[float]:
    if not returns_map:
        return []
    max_len = max(len(values) for values in returns_map.values())
    if max_len == 0:
        return []
    combined = [0.0] * max_len
    for key, values in returns_map.items():
        weight = float(positions.get(key, 0.0))
        for index, value in enumerate(values):
            combined[index] += weight * float(value)
    return combined


def _historical_var(returns: Sequence[float], confidence: float) -> float:
    if not returns:
        return 0.0
    if confidence <= 0 or confidence >= 1:
        return 0.0
    ordered = sorted(float(value) for value in returns)
    if not ordered:
        return 0.0
    tail_probability = max(0.0, min(1.0, 1.0 - confidence))
    if tail_probability == 0.0:
        quantile = ordered[0]
    else:
        position = (len(ordered) - 1) * tail_probability
        lower = math.floor(position)
        upper = math.ceil(position)
        if lower == upper:
            quantile = ordered[int(position)]
        else:
            weight = position - lower
            quantile = ordered[lower] * (1.0 - weight) + ordered[upper] * weight
    return max(0.0, -quantile)


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
        self.portfolio_config = self._resolve_portfolio_config()
        self._portfolio_metrics_cache: Dict[Path, Dict[str, Any]] = {}
        self.active_constraints = self.config.constraints_for(self.portfolio_config)

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

    def _resolve_portfolio_config(self) -> Optional[PortfolioConfig]:
        override = getattr(self.args, "portfolio_config", None)
        if override:
            override_path = Path(str(override))
            if not override_path.is_absolute():
                override_path = (ROOT / override_path).resolve()
            if not override_path.exists():
                raise FileNotFoundError(f"portfolio configuration override not found: {override_path}")
            payload = yaml.safe_load(override_path.read_text(encoding="utf-8")) or {}
            if not isinstance(payload, Mapping):
                raise ValueError("portfolio configuration override must be a mapping")
            block = payload.get("portfolio") if isinstance(payload.get("portfolio"), Mapping) else payload
            if not isinstance(block, Mapping):
                raise ValueError("portfolio configuration override missing 'portfolio' mapping")
            return PortfolioConfig.from_dict(block)
        return self.config.portfolio

    def _load_portfolio_metrics(self, path: Path) -> Optional[Mapping[str, Any]]:
        cache_key = path.resolve()
        cached = self._portfolio_metrics_cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            payload = json.loads(cache_key.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, Mapping):
            return None
        self._portfolio_metrics_cache[cache_key] = dict(payload)
        return self._portfolio_metrics_cache[cache_key]

    def _compute_portfolio_report(
        self,
        *,
        manifest_path: Path,
        metrics_data: Mapping[str, Any],
    ) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        cfg = self.portfolio_config
        if not cfg:
            return None, None
        telemetry_payload: Dict[str, Any] = {}
        if cfg.telemetry_path:
            try:
                telemetry_payload = json.loads(cfg.telemetry_path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                telemetry_payload = {}
            except json.JSONDecodeError:
                telemetry_payload = {}
        if cfg.telemetry:
            telemetry_payload.update(copy.deepcopy(cfg.telemetry))
        telemetry = PortfolioTelemetry(**telemetry_payload)
        manifests: List[Any] = []
        positions: Dict[str, float] = {}
        strategies_summary: List[Dict[str, Any]] = []
        returns_map: Dict[str, List[float]] = {}
        base_equity_map: Dict[str, float] = {}
        errors: List[str] = []

        for strategy_cfg in cfg.strategies:
            if strategy_cfg.use_trial_manifest:
                manifest_source = manifest_path
            else:
                if not strategy_cfg.manifest_path:
                    errors.append(f"strategy {strategy_cfg.id} missing manifest_path")
                    continue
                manifest_source = strategy_cfg.manifest_path
            try:
                manifest = load_manifest(manifest_source)
            except FileNotFoundError as exc:
                errors.append(str(exc))
                continue
            manifests.append(manifest)
            strategy_id = manifest.id
            positions[strategy_id] = float(strategy_cfg.position)
            telemetry.active_positions[strategy_id] = int(round(strategy_cfg.position))
            metrics_payload: Optional[Mapping[str, Any]]
            if strategy_cfg.use_trial_metrics:
                metrics_payload = metrics_data
            else:
                metrics_payload = None
                if strategy_cfg.metrics_path:
                    metrics_payload = self._load_portfolio_metrics(strategy_cfg.metrics_path)
                    if metrics_payload is None:
                        errors.append(
                            f"metrics not found for strategy {strategy_cfg.id}: {strategy_cfg.metrics_path}"
                        )
            curve_raw = metrics_payload.get("equity_curve") if metrics_payload else None
            curve = _normalise_equity_curve(curve_raw)
            returns, base_equity = _curve_returns(curve)
            if returns:
                returns_map[strategy_id] = returns
            if base_equity:
                base_equity_map[strategy_id] = base_equity
            summary_entry = {
                "id": strategy_id,
                "name": manifest.name,
                "position": float(strategy_cfg.position),
                "use_trial_manifest": strategy_cfg.use_trial_manifest,
                "use_trial_metrics": strategy_cfg.use_trial_metrics,
            }
            if strategy_cfg.manifest_path:
                summary_entry["manifest_path"] = _relative_path(strategy_cfg.manifest_path)
            else:
                summary_entry["manifest_path"] = _relative_path(manifest_path)
            if strategy_cfg.metrics_path:
                summary_entry["metrics_path"] = _relative_path(strategy_cfg.metrics_path)
            strategies_summary.append(summary_entry)

        if not manifests:
            return None, None

        portfolio_state = build_portfolio_state(manifests, telemetry=telemetry)
        state_payload: Dict[str, Any] = {
            "active_positions": dict(portfolio_state.active_positions),
            "category_utilisation_pct": dict(portfolio_state.category_utilisation_pct),
            "category_caps_pct": dict(portfolio_state.category_caps_pct),
            "category_headroom_pct": dict(portfolio_state.category_headroom_pct),
            "category_budget_pct": dict(portfolio_state.category_budget_pct),
            "category_budget_headroom_pct": dict(portfolio_state.category_budget_headroom_pct),
            "gross_exposure_pct": portfolio_state.gross_exposure_pct,
            "gross_exposure_cap_pct": portfolio_state.gross_exposure_cap_pct,
            "gross_exposure_headroom_pct": portfolio_state.gross_exposure_headroom_pct,
            "strategy_correlations": dict(portfolio_state.strategy_correlations),
            "correlation_meta": portfolio_state.correlation_meta,
            "correlation_window_minutes": portfolio_state.correlation_window_minutes,
        }
        if portfolio_state.execution_health:
            state_payload["execution_health"] = portfolio_state.execution_health

        per_strategy_var = {
            key: _historical_var(values, cfg.var.confidence)
            for key, values in returns_map.items()
            if values
        }
        aggregated_returns = _combine_returns(returns_map, positions)
        portfolio_var_pct = _historical_var(aggregated_returns, cfg.var.confidence)
        base_equity = float(self.config.runner_equity or 0.0)
        if base_equity <= 0:
            base_equity = next((value for value in base_equity_map.values() if value > 0), 0.0)
        if base_equity <= 0 and base_equity_map:
            weighted_sum = 0.0
            weight_total = 0.0
            for key, value in base_equity_map.items():
                weight = abs(positions.get(key, 0.0))
                weighted_sum += value * weight
                weight_total += weight
            if weight_total > 0:
                base_equity = weighted_sum / weight_total
        var_payload: Dict[str, Any] = {
            "confidence": cfg.var.confidence,
            "horizon_days": cfg.var.horizon_days,
            "portfolio_pct": portfolio_var_pct,
        }
        if base_equity > 0:
            var_payload["portfolio_value"] = portfolio_var_pct * base_equity
        if per_strategy_var:
            var_payload["per_strategy_pct"] = per_strategy_var

        positions_payload = {key: float(value) for key, value in positions.items()}
        portfolio_payload: Dict[str, Any] = {
            "strategies": strategies_summary,
            "positions": positions_payload,
            "state": state_payload,
            "var": var_payload,
        }
        if cfg.telemetry_path:
            portfolio_payload["telemetry_source"] = _relative_path(cfg.telemetry_path)
        if errors:
            portfolio_payload["errors"] = errors

        portfolio_context = {
            "positions": positions_payload,
            "state": state_payload,
            "var": var_payload,
        }
        return portfolio_payload, portfolio_context

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
        if spec.metadata:
            metadata["search_metadata"] = copy.deepcopy(spec.metadata)
        if self.dataset_fingerprint:
            metadata["dataset"] = self.dataset_fingerprint
        if self.args.dry_run:
            metadata.update({"status": "dry_run", "duration_seconds": 0.0})
            _write_json(result_path, metadata)
            return TrialResult(spec=spec, status="dry_run", result_path=result_path, payload=metadata)
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
            return TrialResult(spec=spec, status="failed", result_path=result_path, payload=metadata)
        run_dir = _discover_run_dir(trial_dir)
        if not run_dir:
            metadata.update({"status": "error", "error": "run directory not created"})
            _write_json(result_path, metadata)
            return TrialResult(spec=spec, status="error", result_path=result_path, payload=metadata)
        metrics_path = run_dir / "metrics.json"
        daily_path = run_dir / "daily.csv"
        try:
            metrics_data = json.loads(metrics_path.read_text(encoding="utf-8"))
            daily_frame = pd.read_csv(daily_path)
        except FileNotFoundError:
            metadata.update({"status": "error", "error": "missing metrics or daily outputs"})
            _write_json(result_path, metadata)
            return TrialResult(spec=spec, status="error", result_path=result_path, payload=metadata)
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
        portfolio_payload, portfolio_context = self._compute_portfolio_report(
            manifest_path=manifest_override, metrics_data=metrics_data
        )
        context = self.config.make_context(
            params=spec.params,
            metrics=summary,
            seasonal=seasonal,
            portfolio=portfolio_context,
        )
        constraints, feasible = evaluate_constraints(context, self.active_constraints)
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
        if portfolio_payload is not None:
            metadata["portfolio"] = portfolio_payload
        history_info = self._log_history(run_dir, command_str)
        if history_info:
            metadata["history"] = history_info
        _write_json(result_path, metadata)
        return TrialResult(spec=spec, status="completed", result_path=result_path, payload=metadata)

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


class BayesSearchRunner:
    """Sequential Bayesian-style search helper with optional Optuna integration."""

    def __init__(
        self,
        runner: SweepRunner,
        *,
        output_dir: Path,
        timestamp: str,
    ) -> None:
        self.runner = runner
        self.output_dir = output_dir
        self.timestamp = timestamp
        self.config = runner.config
        self.args = runner.args
        base_bayes = self.config.bayes
        if base_bayes is not None:
            self.bayes_config = base_bayes
        else:
            self.bayes_config = BayesConfig(
                enabled=False,
                seed=None,
                acquisition=None,
                exploration_upper_bound=None,
                initial_random_trials=3,
                constraint_retry_limit=0,
                transforms={},
            )
        if getattr(self.args, "seed", None) is not None:
            self.master_seed = int(self.args.seed)
        elif self.bayes_config.seed is not None:
            self.master_seed = int(self.bayes_config.seed)
        else:
            self.master_seed = int(time.time())
        self.rng = random.Random(self.master_seed)
        self.suggestion_total = 0
        self.retry_total = 0
        self.history: List[TrialResult] = []
        self._seen_params: set[Tuple[Tuple[str, Any], ...]] = set()
        self.fallback_message: Optional[str] = None
        self._optuna = None
        self.optuna_available = self._check_optuna()
        self.optimizer_name = "optuna" if self.optuna_available else "heuristic"

    def _check_optuna(self) -> bool:
        try:
            import optuna  # type: ignore import
        except ModuleNotFoundError:
            self.fallback_message = (
                "Optuna is not installed; falling back to heuristic sampler for Bayesian search."
            )
            self._optuna = None
            return False
        self._optuna = optuna
        return True

    def _dimension_bounds(self, dimension, hint) -> Tuple[Optional[float], Optional[float]]:
        if hint and hint.bounds:
            return hint.bounds
        if dimension.kind in {"float_range", "range"}:
            minimum = dimension.minimum
            maximum = dimension.maximum
            if minimum is None or maximum is None:
                return None, None
            return float(minimum), float(maximum)
        return None, None

    def _sample_continuous(self, dimension, hint, lower: float, upper: float) -> float:
        if lower >= upper:
            value = lower
        else:
            if hint and hint.transform == "log":
                low = max(lower, 1e-9)
                high = max(upper, low * (1.0 + 1e-9))
                value = math.exp(self.rng.uniform(math.log(low), math.log(high)))
            else:
                value = self.rng.uniform(lower, upper)
        if dimension.kind == "float_range":
            precision = dimension.precision if dimension.precision is not None else 3
            return round(value, precision)
        if dimension.kind == "range":
            step = int(dimension.step or 1)
            return int(round(value / step) * step)
        return value

    def _sample_dimension(self, dimension, hint) -> Any:
        mode = hint.mode if hint else "auto"
        if mode == "auto":
            if dimension.kind == "float_range":
                mode = "continuous"
            elif dimension.kind == "range":
                mode = "discrete"
            else:
                mode = "categorical"
        if mode == "continuous":
            lower, upper = self._dimension_bounds(dimension, hint)
            if lower is None or upper is None:
                return dimension.sample(self.rng)
            return self._sample_continuous(dimension, hint, lower, upper)
        if mode == "discrete" and dimension.kind == "range":
            lower, upper = self._dimension_bounds(dimension, hint)
            if lower is None or upper is None:
                return dimension.sample(self.rng)
            step = int(dimension.step or 1)
            count = max(0, int((upper - lower) / step))
            return int(lower + step * self.rng.randint(0, count))
        return dimension.sample(self.rng)

    def _sample_random_params(self) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        for dimension in self.config.dimensions:
            hint = self.bayes_config.transforms.get(dimension.name)
            params[dimension.name] = self._sample_dimension(dimension, hint)
        return params

    def _mutate_choice(self, dimension, current: Any) -> Any:
        values = dimension.discrete_values()
        if not values:
            return current
        alternatives = [candidate for candidate in values if candidate != current]
        if not alternatives:
            return current if current is not None else values[0]
        if current is not None and self.rng.random() < 0.5:
            return current
        return self.rng.choice(alternatives)

    def _mutate_integer(self, dimension, current: Any) -> Any:
        if current is None:
            return self._sample_dimension(dimension, self.bayes_config.transforms.get(dimension.name))
        step = int(dimension.step or 1)
        lower = int(dimension.minimum) if dimension.minimum is not None else current
        upper = int(dimension.maximum) if dimension.maximum is not None else current
        delta = step if self.rng.random() < 0.5 else -step
        candidate = current + delta
        if candidate < lower or candidate > upper:
            candidate = current
        return candidate

    def _mutate_continuous(self, dimension, hint, current: Any) -> Any:
        lower, upper = self._dimension_bounds(dimension, hint)
        if lower is None or upper is None:
            return self._sample_dimension(dimension, hint)
        if current is None:
            base = (lower + upper) / 2.0
        else:
            try:
                base = float(current)
            except (TypeError, ValueError):
                base = (lower + upper) / 2.0
        span = max(upper - lower, 1e-9)
        sigma = span / 6.0
        candidate = base + self.rng.gauss(0.0, sigma)
        candidate = min(max(candidate, lower), upper)
        return self._sample_continuous(dimension, hint, candidate, candidate)

    def _mutate_params(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        base_params = dict(payload.get("params") or {})
        for dimension in self.config.dimensions:
            hint = self.bayes_config.transforms.get(dimension.name)
            current = base_params.get(dimension.name)
            mode = hint.mode if hint else "auto"
            if mode == "auto":
                if dimension.kind == "float_range":
                    mode = "continuous"
                elif dimension.kind == "range":
                    mode = "discrete"
                else:
                    mode = "categorical"
            if mode == "continuous":
                params[dimension.name] = self._mutate_continuous(dimension, hint, current)
            elif mode == "discrete" and dimension.kind == "range":
                params[dimension.name] = self._mutate_integer(dimension, current)
            else:
                params[dimension.name] = self._mutate_choice(dimension, current)
        return params

    def _best_payload(self) -> Optional[Dict[str, Any]]:
        completed = [item for item in self.history if item.status == "completed"]
        feasible = [item for item in completed if bool((item.payload or {}).get("feasible"))]
        candidates = feasible or completed
        if not candidates:
            return None

        def score_key(item: TrialResult) -> float:
            payload = item.payload or {}
            score = payload.get("score")
            try:
                return float(score)
            except (TypeError, ValueError):
                return float("-inf")

        return max(candidates, key=score_key).payload

    def _propose_params(self, suggestion_index: int, attempt_index: int) -> Dict[str, Any]:
        phase = "explore" if suggestion_index <= self.bayes_config.initial_random_trials else "exploit"
        if phase == "explore" or not self.history:
            return self._sample_random_params()
        base_payload = self._best_payload()
        if not base_payload:
            return self._sample_random_params()
        params = self._mutate_params(base_payload)
        if attempt_index > 1 and self.rng.random() < 0.5:
            return self._sample_random_params()
        return params

    def _build_search_metadata(
        self,
        *,
        suggestion_index: int,
        attempt_index: int,
        seed: int,
    ) -> Dict[str, Any]:
        phase = "explore" if suggestion_index <= self.bayes_config.initial_random_trials else "exploit"
        metadata: Dict[str, Any] = {
            "strategy": "bayes",
            "suggestion_index": suggestion_index,
            "retry": max(0, attempt_index - 1),
            "phase": phase,
            "seed": seed,
            "optimizer": self.optimizer_name,
            "optuna_available": self.optuna_available,
        }
        if self.bayes_config.acquisition:
            metadata["acquisition"] = {
                "name": self.bayes_config.acquisition.name,
                "parameters": dict(self.bayes_config.acquisition.parameters),
            }
        if self.bayes_config.exploration_upper_bound is not None:
            metadata["exploration_upper_bound"] = self.bayes_config.exploration_upper_bound
        if self.fallback_message:
            metadata["fallback"] = self.fallback_message
        return metadata

    def run(self, max_trials: int) -> Tuple[List[TrialResult], Dict[str, Any]]:
        results: List[TrialResult] = []
        evaluation_limit = max_trials if max_trials and max_trials > 0 else None
        suggestion_limit = self.bayes_config.exploration_upper_bound
        break_outer = False
        while True:
            if evaluation_limit is not None and len(results) >= evaluation_limit:
                break
            if suggestion_limit is not None and self.suggestion_total >= suggestion_limit:
                break
            suggestion_index = self.suggestion_total + 1
            attempts_for_suggestion = 0
            while True:
                if evaluation_limit is not None and len(results) >= evaluation_limit:
                    break_outer = True
                    break
                attempts_for_suggestion += 1
                params = self._propose_params(suggestion_index, attempts_for_suggestion)
                key = tuple(sorted(params.items()))
                dedupe_attempts = 0
                while key in self._seen_params and dedupe_attempts < 10:
                    params = self._sample_random_params()
                    key = tuple(sorted(params.items()))
                    dedupe_attempts += 1
                self._seen_params.add(key)
                seed = self.rng.randrange(1, 2**32 - 1)
                metadata = self._build_search_metadata(
                    suggestion_index=suggestion_index,
                    attempt_index=attempts_for_suggestion,
                    seed=seed,
                )
                spec = TrialSpec(
                    index=len(results),
                    params=params,
                    seed=seed,
                    token=_build_trial_token(self.timestamp, seed),
                    metadata=metadata,
                )
                trial_dir = self.output_dir / spec.token
                result = self.runner._run_single(spec, trial_dir)
                results.append(result)
                self.history.append(result)
                payload = result.payload or {}
                feasible = bool(payload.get("feasible")) if result.status == "completed" else False
                if result.status != "completed":
                    break
                if feasible:
                    break
                if attempts_for_suggestion > self.bayes_config.constraint_retry_limit:
                    break
            self.suggestion_total += 1
            self.retry_total += max(0, attempts_for_suggestion - 1)
            if break_outer:
                break
        meta: Dict[str, Any] = {
            "enabled": bool(self.config.bayes and self.config.bayes.enabled),
            "seed": self.master_seed,
            "initial_random_trials": self.bayes_config.initial_random_trials,
            "suggestions": self.suggestion_total,
            "evaluations": len(results),
            "constraint_retries": self.retry_total,
            "optimizer": self.optimizer_name,
            "optuna_available": self.optuna_available,
        }
        if self.bayes_config.acquisition:
            meta["acquisition"] = {
                "name": self.bayes_config.acquisition.name,
                "parameters": dict(self.bayes_config.acquisition.parameters),
            }
        if self.bayes_config.exploration_upper_bound is not None:
            meta["exploration_upper_bound"] = self.bayes_config.exploration_upper_bound
        if self.fallback_message:
            meta["fallback_message"] = self.fallback_message
        return results, meta


def _prepare_trials(config: ExperimentConfig, args: argparse.Namespace, timestamp: str) -> List[TrialSpec]:
    plans: List[TrialSpec] = []
    space_size = config.search_space_size()
    limit = args.max_trials if args.max_trials and args.max_trials > 0 else space_size
    if args.search == "bayes":
        raise NotImplementedError("Bayesian search plans are generated by BayesSearchRunner")
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
    runner = SweepRunner(config, args, timestamp=timestamp)
    bayes_meta: Optional[Dict[str, Any]] = None
    plans: List[TrialSpec] = []
    results: List[TrialResult] = []
    if args.search == "bayes":
        bayes_runner = BayesSearchRunner(runner, output_dir=output_dir, timestamp=timestamp)
        results, bayes_meta = bayes_runner.run(args.max_trials)
        total_trials = bayes_meta.get("evaluations", len(results)) if bayes_meta else len(results)
    else:
        try:
            plans = _prepare_trials(config, args, timestamp)
        except NotImplementedError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        results = runner.run_trials(plans, output_dir)
        total_trials = len(plans)
    completed = sum(1 for item in results if item.status == "completed")
    failures = sum(1 for item in results if item.status not in {"completed", "dry_run"})
    summary = {
        "experiment": config.identifier,
        "config_path": _relative_path(config.path),
        "timestamp": utcnow_iso(),
        "search": args.search,
        "total_trials": total_trials,
        "completed": completed,
        "failures": failures,
        "dry_run": args.dry_run,
    }
    if bayes_meta:
        summary["bayes"] = bayes_meta
    _write_json(output_dir / "sweep_summary.json", summary)
    _write_sweep_log(config, output_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if failures == 0 else 1


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())
