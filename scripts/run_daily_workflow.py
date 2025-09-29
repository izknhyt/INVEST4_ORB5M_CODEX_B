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
    parser.add_argument(
        "--ingest-source",
        default=None,
        help="Override source CSV path passed to pull_prices.py",
    )
    parser.add_argument("--update-state", action="store_true", help="Replay new bars and update state.json")
    parser.add_argument("--benchmarks", action="store_true", help="Run baseline + rolling benchmarks")
    parser.add_argument("--state-health", action="store_true", help="Run state health checker")
    parser.add_argument("--benchmark-summary", action="store_true", help="Aggregate benchmark reports")
    parser.add_argument(
        "--check-benchmark-freshness",
        action="store_true",
        help="Validate benchmark timestamps recorded in runtime snapshot",
    )
    parser.add_argument("--benchmark-windows", default="365,180,90", help="Rolling windows in days for benchmarks")
    parser.add_argument(
        "--min-sharpe",
        type=float,
        default=None,
        help="Warn when Sharpe ratio falls below this value",
    )
    parser.add_argument(
        "--min-win-rate",
        type=float,
        default=None,
        help="Warn when win_rate falls below this value",
    )
    parser.add_argument(
        "--max-drawdown",
        type=float,
        default=None,
        help="Warn when |max_drawdown| exceeds this value (pips)",
    )
    parser.add_argument(
        "--alert-pips",
        type=float,
        default=50.0,
        help="Abs diff in total_pips to trigger alert",
    )
    parser.add_argument(
        "--alert-winrate",
        type=float,
        default=0.05,
        help="Abs diff in win_rate to trigger alert",
    )
    parser.add_argument(
        "--alert-sharpe",
        type=float,
        default=0.15,
        help="Abs diff in Sharpe ratio to trigger alert",
    )
    parser.add_argument(
        "--alert-max-drawdown",
        type=float,
        default=40.0,
        help="Abs diff in max_drawdown (pips) to trigger alert",
    )
    parser.add_argument("--optimize", action="store_true", help="Run parameter optimization")
    parser.add_argument("--analyze-latency", action="store_true", help="Analyze signal latency")
    parser.add_argument("--archive-state", action="store_true", help="Archive state.json files")
    parser.add_argument("--bars", default=None, help="Override bars CSV path (default: validated/<symbol>/5m.csv)")
    parser.add_argument("--webhook", default=None)
    parser.add_argument(
        "--benchmark-freshness-max-age-hours",
        type=float,
        default=None,
        help="Override max age threshold (hours) for benchmark freshness checks",
    )
    parser.add_argument(
        "--benchmark-freshness-targets",
        default=None,
        help="Comma-separated symbol:mode targets for freshness checks",
    )
    args = parser.parse_args(argv)

    bars_csv = args.bars or str(ROOT / f"validated/{args.symbol}/5m.csv")

    if args.ingest:
        ingest_source = args.ingest_source or str(ROOT / "data/usdjpy_5m_2018-2024_utc.csv")
        cmd = [
            sys.executable,
            str(ROOT / "scripts/pull_prices.py"),
            "--source",
            ingest_source,
            "--symbol",
            args.symbol,
        ]
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
        # Use the pipeline script which orchestrates runs and summary
        cmd = [
            sys.executable,
            str(ROOT / "scripts/run_benchmark_pipeline.py"),
            "--bars",
            bars_csv,
            "--symbol",
            args.symbol,
            "--mode",
            args.mode,
            "--equity",
            str(args.equity),
            "--windows",
            args.benchmark_windows,
        ]
        if args.alert_pips is not None:
            cmd += ["--alert-pips", str(args.alert_pips)]
        if args.alert_winrate is not None:
            cmd += ["--alert-winrate", str(args.alert_winrate)]
        if args.alert_sharpe is not None:
            cmd += ["--alert-sharpe", str(args.alert_sharpe)]
        if args.alert_max_drawdown is not None:
            cmd += ["--alert-max-drawdown", str(args.alert_max_drawdown)]
        if args.min_sharpe is not None:
            cmd += ["--min-sharpe", str(args.min_sharpe)]
        if args.min_win_rate is not None:
            cmd += ["--min-win-rate", str(args.min_win_rate)]
        if args.max_drawdown is not None:
            cmd += ["--max-drawdown", str(args.max_drawdown)]
        if args.webhook:
            cmd += ["--webhook", args.webhook]
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
        cmd = [
            sys.executable,
            str(ROOT / "scripts/report_benchmark_summary.py"),
            "--symbol",
            args.symbol,
            "--mode",
            args.mode,
            "--reports-dir",
            str(ROOT / "reports"),
            "--json-out",
            str(ROOT / "reports/benchmark_summary.json"),
            "--plot-out",
            str(ROOT / "reports/benchmark_summary.png"),
            "--windows",
            args.benchmark_windows,
        ]
        if args.min_sharpe is not None:
            cmd += ["--min-sharpe", str(args.min_sharpe)]
        if args.min_win_rate is not None:
            cmd += ["--min-win-rate", str(args.min_win_rate)]
        if args.max_drawdown is not None:
            cmd += ["--max-drawdown", str(args.max_drawdown)]
        if args.webhook:
            cmd += ["--webhook", args.webhook]
        exit_code = run_cmd(cmd)
        if exit_code:
            return exit_code

    if args.check_benchmark_freshness:
        cmd = [
            sys.executable,
            str(ROOT / "scripts/check_benchmark_freshness.py"),
            "--snapshot",
            str(ROOT / "ops/runtime_snapshot.json"),
            "--max-age-hours",
            str(
                args.benchmark_freshness_max_age_hours
                if args.benchmark_freshness_max_age_hours is not None
                else 6.0
            ),
        ]
        if args.benchmark_freshness_targets:
            for raw_target in args.benchmark_freshness_targets.split(","):
                target = raw_target.strip()
                if target:
                    cmd += ["--target", target]
        else:
            cmd += ["--target", f"{args.symbol}:{args.mode}"]
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
