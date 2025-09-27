#!/usr/bin/env python3
"""Compare metrics JSON against target thresholds."""
from __future__ import annotations
import argparse
import json
from pathlib import Path


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Evaluate performance metrics against targets")
    p.add_argument("--metrics", required=True, help="Path to JSON file with metrics")
    p.add_argument("--targets", default="configs/targets.json", help="Target thresholds JSON")
    p.add_argument("--json-out", default=None)
    return p.parse_args(argv)


def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def evaluate(metrics: dict, targets: dict) -> dict:
    results = {}
    # Expectation of keys
    sharpe = float(metrics.get("sharpe", 0.0))
    results["sharpe_min"] = sharpe >= targets.get("sharpe_min", sharpe)

    max_dd = float(metrics.get("max_drawdown", 0.0))
    results["max_dd_max"] = abs(max_dd) <= targets.get("max_dd_max", abs(max_dd))

    pf = float(metrics.get("profit_factor", 0.0))
    results["profit_factor_min"] = pf >= targets.get("profit_factor_min", pf)

    expectancy = float(metrics.get("expectancy", 0.0))
    results["expectancy_min"] = expectancy >= targets.get("expectancy_min", expectancy)

    cagr = float(metrics.get("cagr", 0.0))
    results["cagr_min"] = cagr >= targets.get("cagr_min", cagr)

    overall = all(results.values())
    return {
        "metrics": metrics,
        "targets": targets,
        "results": results,
        "passed": overall,
    }


def main(argv=None) -> int:
    args = parse_args(argv)
    metrics = load_json(Path(args.metrics))
    targets = load_json(Path(args.targets))
    summary = evaluate(metrics, targets)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
