#!/usr/bin/env python3
"""Select the best parameter combinations from sweep results."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts._param_sweep import (  # noqa: E402
    ExperimentConfig,
    evaluate_constraints,
    load_experiment_config,
)
from scripts._time_utils import utcnow_iso  # noqa: E402


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", required=True, help="Experiment config name or path")
    parser.add_argument("--runs-dir", help="Directory containing sweep trial folders")
    parser.add_argument("--top-k", type=int, default=5, help="Number of candidates to keep")
    parser.add_argument("--out", help="Output path for best parameter JSON")
    parser.add_argument("--include-infeasible", action="store_true", help="List infeasible trials in the output")
    return parser.parse_args(argv)


def _load_trial_results(runs_dir: Path) -> Iterable[Path]:
    for entry in sorted(runs_dir.iterdir()):
        if not entry.is_dir():
            continue
        result_path = entry / "result.json"
        if result_path.exists():
            yield result_path


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _relative(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _build_candidate(
    config: ExperimentConfig,
    payload: Dict[str, Any],
    result_path: Path,
) -> Dict[str, Any]:
    status = payload.get("status", "unknown")
    params = payload.get("params", {})
    metrics = payload.get("metrics", {})
    seasonal = payload.get("seasonal", {})
    context = config.make_context(params=params, metrics=metrics, seasonal=seasonal)
    constraints, feasible = evaluate_constraints(context, config.constraints)
    score, breakdown = config.scoring.compute(context)
    tie_key = config.scoring.tie_breaker_key(context)
    candidate = {
        "trial_id": payload.get("trial_id"),
        "seed": payload.get("seed"),
        "status": status,
        "feasible": feasible and status == "completed",
        "score": score,
        "score_breakdown": breakdown,
        "tie_breaker_key": list(tie_key),
        "tie_breakers": config.scoring.tie_breaker_values(context),
        "constraints": constraints,
        "params": params,
        "metrics": metrics,
        "seasonal": seasonal,
        "run_dir": payload.get("run_dir"),
        "command": payload.get("command_str") or payload.get("command"),
        "history": payload.get("history"),
        "result_path": _relative(result_path),
    }
    return candidate


def _sort_candidates(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def sort_key(item: Dict[str, Any]):
        feasible_flag = 1 if item.get("feasible") else 0
        score = item.get("score") or 0.0
        tie_key = item.get("tie_breaker_key") or []
        return (feasible_flag, score, *tie_key)

    return sorted(candidates, key=sort_key, reverse=True)


def _summarise_constraints(candidate: Dict[str, Any]) -> Dict[str, Any]:
    constraints = candidate.get("constraints") or {}
    failed = [cid for cid, entry in constraints.items() if entry.get("status") not in {"pass", "unknown"}]
    return {"passed": len(constraints) - len(failed), "failed": failed}


def _build_payload(
    config: ExperimentConfig,
    runs_dir: Path,
    candidates: List[Dict[str, Any]],
    *,
    top_k: int,
    include_infeasible: bool,
) -> Dict[str, Any]:
    completed = [item for item in candidates if item.get("status") == "completed"]
    feasible = [item for item in completed if item.get("feasible")]
    ranking = feasible[:top_k]
    for idx, item in enumerate(ranking, start=1):
        item["rank"] = idx
        item["constraints_summary"] = _summarise_constraints(item)
    payload: Dict[str, Any] = {
        "experiment": config.identifier,
        "config_path": _relative(config.path),
        "generated_at": utcnow_iso(),
        "runs_dir": _relative(runs_dir),
        "top_k": top_k,
        "trials": {
            "total": len(candidates),
            "completed": len(completed),
            "feasible": len(feasible),
        },
        "ranking": ranking,
    }
    if include_infeasible:
        infeasible = [item for item in completed if not item.get("feasible")]
        for entry in infeasible:
            entry["constraints_summary"] = _summarise_constraints(entry)
        payload["infeasible"] = infeasible
    if config.history_notes:
        payload["notes"] = config.history_notes
    return payload


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)
    config = load_experiment_config(args.experiment)
    runs_dir = Path(args.runs_dir) if args.runs_dir else config.base_output_dir
    runs_dir = runs_dir.resolve()
    if not runs_dir.exists():
        print(f"Runs directory not found: {runs_dir}", file=sys.stderr)
        return 2
    candidates: List[Dict[str, Any]] = []
    for result_path in _load_trial_results(runs_dir):
        payload = _load_json(result_path)
        candidate = _build_candidate(config, payload, result_path)
        candidates.append(candidate)
    if not candidates:
        print("No trial results found", file=sys.stderr)
        return 1
    candidates = _sort_candidates(candidates)
    reports_dir = Path(args.out) if args.out else ROOT / "reports" / "simulations" / config.identifier
    if reports_dir.suffix:
        out_path = reports_dir
    else:
        reports_dir.mkdir(parents=True, exist_ok=True)
        out_path = reports_dir / "best_params.json"
    payload = _build_payload(
        config,
        runs_dir,
        candidates,
        top_k=args.top_k,
        include_infeasible=args.include_infeasible,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": _relative(out_path), "feasible": payload["trials"]["feasible"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())
