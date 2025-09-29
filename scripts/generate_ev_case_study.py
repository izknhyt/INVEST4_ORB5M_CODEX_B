#!/usr/bin/env python3
"""Parameter sweep runner for EV tuning experiments."""
from __future__ import annotations

import argparse
import csv
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ev_sweep import (  # noqa: E402
    build_dimensions,
    build_csv_row,
    compute_derived,
    iter_param_combinations,
)
from scripts.run_sim import main as run_sim_main  # noqa: E402


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Generate EV parameter sweep summaries")
    p.add_argument(
        "--base-args",
        nargs=argparse.REMAINDER,
        default=[],
        help="Base arguments for run_sim (例: --csv data.csv --symbol USDJPY ...)",
    )
    p.add_argument(
        "--threshold",
        "--threshold-lcb",
        dest="threshold",
        type=float,
        action="append",
        help="threshold_lcb values to test",
    )
    p.add_argument(
        "--decay",
        type=float,
        action="append",
        help="EV decay coefficients to test",
    )
    p.add_argument(
        "--prior-alpha",
        type=float,
        action="append",
        help="prior_alpha values to test",
    )
    p.add_argument(
        "--prior-beta",
        type=float,
        action="append",
        help="prior_beta values to test",
    )
    p.add_argument(
        "--warmup",
        type=int,
        action="append",
        help="Warmup trade counts to test (default: 10)",
    )
    p.add_argument(
        "--no-warmup",
        action="store_true",
        help="Do not override warmup trades (use runner defaults)",
    )
    p.add_argument(
        "--dump-max",
        type=int,
        default=1000,
        help="Max number of sample records to dump per run",
    )
    p.add_argument(
        "--output",
        "--output-json",
        dest="output_json",
        default="analysis/ev_param_sweep.json",
        help="Path to write aggregated JSON",
    )
    p.add_argument(
        "--output-csv",
        dest="output_csv",
        default="analysis/ev_param_sweep.csv",
        help="Path to write aggregated CSV",
    )
    return p.parse_args(argv)


def _ensure_parent(path: Path) -> None:
    if not path:
        return
    path.parent.mkdir(parents=True, exist_ok=True)


def _clean_metrics(metrics: Dict[str, Any]) -> Dict[str, Any]:
    cleaned = dict(metrics)
    for key in ("dump_csv", "dump_rows", "dump_daily"):
        cleaned.pop(key, None)
    return cleaned


def main(argv=None) -> int:
    args = parse_args(argv)
    dimensions = build_dimensions(args)
    base_args = list(args.base_args)
    if not base_args:
        raise SystemExit("--base-args must include run_sim parameters")

    results: List[Dict[str, Any]] = []
    csv_rows: List[Dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="ev_sweep_") as tmpdir:
        temp_dir = Path(tmpdir)
        for idx, combo in enumerate(iter_param_combinations(dimensions)):
            params = {k: v for k, v in combo.items() if v is not None}
            override_args: List[str] = []
            for dim in dimensions:
                value = combo.get(dim.key)
                if value is None:
                    continue
                override_args.extend([dim.flag, str(value)])
            metrics_path = temp_dir / f"metrics_{idx}.json"
            daily_path = temp_dir / f"daily_{idx}.csv"
            records_path = temp_dir / f"records_{idx}.csv"
            argv_run = base_args + override_args + [
                "--json-out",
                str(metrics_path),
                "--dump-daily",
                str(daily_path),
                "--dump-csv",
                str(records_path),
                "--dump-max",
                str(args.dump_max),
            ]
            run_sim_main(argv_run)
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
            cleaned_metrics = _clean_metrics(metrics)
            derived = compute_derived(cleaned_metrics)
            results.append({
                "params": params,
                "metrics": cleaned_metrics,
                "derived": derived,
            })
            csv_rows.append(build_csv_row(params, cleaned_metrics))

    output_json = Path(args.output_json) if args.output_json else None
    if output_json:
        _ensure_parent(output_json)
        output_json.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    output_csv = Path(args.output_csv) if args.output_csv else None
    if output_csv:
        _ensure_parent(output_csv)
        fieldnames: List[str] = []
        for row in csv_rows:
            for key in row.keys():
                if key not in fieldnames:
                    fieldnames.append(key)
        with output_csv.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in csv_rows:
                writer.writerow(row)

    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

