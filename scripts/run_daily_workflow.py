#!/usr/bin/env python3
"""Daily workflow orchestration script."""
from __future__ import annotations
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_cmd(cmd):
    print(f"[wf] running: {' '.join(cmd)}")
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        print(f"[wf] command failed with exit code {result.returncode}")
    return result.returncode


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Daily workflow orchestrator")
    parser.add_argument("--symbol", default="USDJPY")
    parser.add_argument("--mode", default="conservative", choices=["conservative", "bridge"])
    parser.add_argument("--equity", default="100000")
    parser.add_argument("--ingest", action="store_true", help="Run pull_prices to append latest bars")
    parser.add_argument("--update-state", action="store_true", help="Replay new bars and update state.json")
    parser.add_argument("--benchmarks", action="store_true", help="Run baseline + rolling benchmarks")
    parser.add_argument("--state-health", action="store_true", help="Run state health checker")
    parser.add_argument("--benchmark-summary", action="store_true", help="Aggregate benchmark reports")
    parser.add_argument("--benchmark-windows", default="365,180,90", help="Rolling windows in days for benchmarks")
    parser.add_argument(
        "--min-sharpe",
        type=float,
        default=None,
        help="Warn when Sharpe ratio falls below this value",
    )
    parser.add_argument(
        "--max-drawdown",
        type=float,
        default=None,
        help="Warn when |max_drawdown| exceeds this value (pips)",
    )
    parser.add_argument("--optimize", action="store_true", help="Run parameter optimization")
    parser.add_argument("--analyze-latency", action="store_true", help="Analyze signal latency")
    parser.add_argument("--archive-state", action="store_true", help="Archive state.json files")
    parser.add_argument("--bars", default=None, help="Override bars CSV path (default: validated/<symbol>/5m.csv)")
    parser.add_argument("--webhook", default=None)
    args = parser.parse_args(argv)

    bars_csv = args.bars or str(ROOT / f"validated/{args.symbol}/5m.csv")

    if args.ingest:
        cmd = [sys.executable, str(ROOT / "scripts/pull_prices.py"),
               "--source", str(ROOT / "data/usdjpy_5m_2018-2024_utc.csv"),
               "--symbol", args.symbol]
        exit_code = run_cmd(cmd)
        if exit_code:
            return exit_code

    if args.update_state:
        cmd = [sys.executable, str(ROOT / "scripts/update_state.py"),
               "--bars", bars_csv,
               "--symbol", args.symbol,
               "--mode", args.mode,
               "--equity", args.equity,
               "--state-out", str(ROOT / "runs/active/state.json")]
        exit_code = run_cmd(cmd)
        if exit_code:
            return exit_code

    if args.benchmarks:
        cmd = [sys.executable, str(ROOT / "scripts/run_benchmark_runs.py"),
               "--bars", bars_csv,
               "--symbol", args.symbol,
               "--mode", args.mode,
               "--equity", args.equity,
               "--windows", args.benchmark_windows]
        exit_code = run_cmd(cmd)
        if exit_code:
            return exit_code

    if args.state_health:
        cmd = [sys.executable, str(ROOT / "scripts/check_state_health.py"),
               "--state", str(ROOT / "runs/active/state.json"),
               "--json-out", str(ROOT / "ops/health/state_checks.json")]
        exit_code = run_cmd(cmd)
        if exit_code:
            return exit_code

    if args.benchmark_summary:
        cmd = [sys.executable, str(ROOT / "scripts/report_benchmark_summary.py"),
               "--symbol", args.symbol,
               "--mode", args.mode,
               "--reports-dir", str(ROOT / "reports"),
               "--json-out", str(ROOT / "reports/benchmark_summary.json"),
               "--plot-out", str(ROOT / "reports/benchmark_summary.png"),
               "--windows", args.benchmark_windows]
        exit_code = run_cmd(cmd)
        if exit_code:
            return exit_code

    if args.optimize:
        cmd = [
            sys.executable,
            str(ROOT / "scripts/auto_optimize.py"),
            "--opt-args",
            "--top-k",
            "5",
            "--min-trades",
            "300",
            "--rebuild-index",
            "--csv",
            str(ROOT / "data/usdjpy_5m_2018-2024_utc.csv"),
            "--symbol",
            "USDJPY",
            "--mode",
            "conservative",
            "--or-n",
            "4,6",
            "--k-tp",
            "0.8,1.0",
            "--k-sl",
            "0.4,0.6",
            "--threshold-lcb",
            "0.3",
            "--allowed-sessions",
            "LDN,NY",
            "--warmup",
            "10",
            "--include-expected-slip",
            "--report",
            str(ROOT / "reports/auto_optimize.json"),
        ]
        if args.webhook:
            cmd += ["--webhook", args.webhook]
        exit_code = run_cmd(cmd)
        if exit_code:
            return exit_code

    if args.analyze_latency:
        cmd = [
            sys.executable,
            str(ROOT / "scripts/analyze_signal_latency.py"),
            "--input",
            str(ROOT / "ops/signal_latency.csv"),
            "--slo-threshold",
            "5",
            "--json-out",
            str(ROOT / "reports/signal_latency.json"),
        ]
        exit_code = run_cmd(cmd)
        if exit_code:
            return exit_code

    if args.archive_state:
        cmd = [
            sys.executable,
            str(ROOT / "scripts/archive_state.py"),
            "--runs-dir",
            str(ROOT / "runs"),
            "--output",
            str(ROOT / "ops/state_archive"),
        ]
        exit_code = run_cmd(cmd)
        if exit_code:
            return exit_code

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
