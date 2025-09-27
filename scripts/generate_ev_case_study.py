#!/usr/bin/env python3
"""Generate EV threshold case study JSON for conservative strategy."""
from __future__ import annotations
import argparse
import json
from pathlib import Path

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_sim import main as run_sim_main


def run_once(args_list):
    argv = list(args_list)
    run_sim_main(argv)


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Generate EV threshold case study")
    p.add_argument("--base-args", nargs=argparse.REMAINDER, default=[],
                   help="Base arguments for run_sim (例: --csv data.csv --symbol USDJPY ...)")
    p.add_argument("--threshold", type=float, action="append", required=True,
                   help="threshold_lcb values to test")
    p.add_argument("--warmup", type=int, default=10)
    p.add_argument("--output", default="analysis/ev_case_study.json")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    results = []
    output_path = Path(args.output)
    base_args = args.base_args
    for threshold in args.threshold:
        metrics_path = Path("/tmp/metrics_case.json")
        daily_path = Path("/tmp/daily_case.csv")
        records_path = Path("/tmp/records_case.csv")
        argv = base_args + [
            "--threshold-lcb", str(threshold),
            "--warmup", str(args.warmup),
            "--json-out", str(metrics_path),
            "--dump-daily", str(daily_path),
            "--dump-csv", str(records_path),
            "--dump-max", "1000",
        ]
        run_once(argv)
        summary = json.loads(metrics_path.read_text())
        summary["threshold_lcb"] = threshold
        results.append(summary)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
