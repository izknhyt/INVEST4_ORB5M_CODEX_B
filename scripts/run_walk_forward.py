#!/usr/bin/env python3
"""Run walk-forward optimization windows."""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

WINDOWS = [
    ("2018-01-01", "2020-12-31", "2021-01-01", "2021-12-31"),
    ("2019-01-01", "2021-12-31", "2022-01-01", "2022-12-31"),
    ("2020-01-01", "2022-12-31", "2023-01-01", "2023-12-31"),
    ("2021-01-01", "2023-12-31", "2024-01-01", "2024-12-31"),
]


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Run walk-forward windows")
    p.add_argument("--csv", default="data/usdjpy_5m_2018-2024_utc.csv")
    p.add_argument("--symbol", default="USDJPY")
    p.add_argument("--mode", default="conservative")
    p.add_argument("--or-n", default="4,6")
    p.add_argument("--k-tp", default="0.8,1.0")
    p.add_argument("--k-sl", default="0.4,0.6")
    p.add_argument("--threshold-lcb", type=float, default=0.3)
    p.add_argument("--allowed-sessions", default="LDN,NY")
    p.add_argument("--warmup", type=int, default=10)
    p.add_argument("--out", default="analysis/walk_forward_log.json")
    return p.parse_args(argv)


def run_optimize(env_vars: dict, args) -> dict:
    cmd = [
        sys.executable,
        str(ROOT / "scripts/optimize_params.py"),
        "--top-k", "3",
        "--min-trades", "200",
        "--csv", args.csv,
        "--symbol", args.symbol,
        "--mode", args.mode,
        "--or-n", args.or_n,
        "--k-tp", args.k_tp,
        "--k-sl", args.k_sl,
        "--threshold-lcb", str(args.threshold_lcb),
        "--allowed-sessions", args.allowed_sessions,
        "--warmup", str(args.warmup)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, env={**os.environ, **env_vars})
    return {
        "cmd": cmd,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode,
    }


def main(argv=None) -> int:
    args = parse_args(argv)
    logs = []
    for train_start, train_end, test_start, test_end in WINDOWS:
        env = {
            "WF_TRAIN_START": train_start,
            "WF_TRAIN_END": train_end,
            "WF_TEST_START": test_start,
            "WF_TEST_END": test_end,
        }
        log = run_optimize(env, args)
        log["window"] = [train_start, train_end, test_start, test_end]
        logs.append(log)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(logs, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(logs, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
