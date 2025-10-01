#!/usr/bin/env python3
"""Daily workflow orchestration script."""
from __future__ import annotations
import argparse
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.utils import yaml_compat as yaml


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
        "--use-dukascopy",
        action="store_true",
        help="Fetch latest bars via Dukascopy before ingestion",
    )
    parser.add_argument(
        "--use-api",
        action="store_true",
        help="Fetch latest bars via REST API before ingestion",
    )
    parser.add_argument(
        "--use-yfinance",
        action="store_true",
        help="Fetch latest bars via yfinance before ingestion",
    )
    parser.add_argument(
        "--dukascopy-lookback-minutes",
        type=int,
        default=180,
        help="Minutes of history to re-request when using Dukascopy ingestion",
    )
    parser.add_argument(
        "--yfinance-lookback-minutes",
        type=int,
        default=60,
        help="Minutes of history to re-request when using yfinance ingestion",
    )
    parser.add_argument(
        "--dukascopy-freshness-threshold-minutes",
        type=int,
        default=90,
        help="Minutes before a Dukascopy fetch is considered stale and triggers fallback",
    )
    parser.add_argument(
        "--api-provider",
        default=None,
        help="Override API provider defined in configs/api_ingest.yml",
    )
    parser.add_argument(
        "--api-config",
        default=str(ROOT / "configs/api_ingest.yml"),
        help="Path to API ingest configuration file",
    )
    parser.add_argument(
        "--api-credentials",
        default=str(ROOT / "configs/api_keys.yml"),
        help="Path to API credential store",
    )
    parser.add_argument(
        "--api-lookback-minutes",
        type=int,
        default=None,
        help="Override history window when using API ingestion",
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

    symbol_input = args.symbol.upper()
    if symbol_input.endswith("=X"):
        symbol_upper = symbol_input[:-2]
    else:
        symbol_upper = symbol_input
    args.symbol = symbol_upper

    bars_csv = args.bars or str(ROOT / f"validated/{symbol_upper}/5m.csv")

    if args.ingest:
        selected_sources = [
            flag
            for flag in (args.use_dukascopy, args.use_api, args.use_yfinance)
            if flag
        ]
        if len(selected_sources) > 1:
            print("[wf] specify at most one of --use-dukascopy/--use-api/--use-yfinance")
            return 1

        if args.use_dukascopy:
            try:
                from scripts.dukascopy_fetch import fetch_bars
                from scripts.pull_prices import ingest_records, get_last_processed_ts
            except RuntimeError as exc:
                print(f"[wf] Dukascopy ingestion unavailable: {exc}")
                return 1

            snapshot_path = ROOT / "ops/runtime_snapshot.json"
            tf = "5m"
            symbol_upper = args.symbol.upper()
            validated_path = ROOT / "validated" / symbol_upper / f"{tf}.csv"
            raw_path = ROOT / "raw" / symbol_upper / f"{tf}.csv"
            features_path = ROOT / "features" / symbol_upper / f"{tf}.csv"

            last_ts = get_last_processed_ts(
                symbol_upper,
                tf,
                snapshot_path=snapshot_path,
                validated_path=validated_path,
            )
            now = datetime.utcnow()
            lookback = max(5, args.dukascopy_lookback_minutes)
            if last_ts is not None:
                start = last_ts - timedelta(minutes=lookback)
            else:
                start = now - timedelta(minutes=lookback)

            print(
                "[wf] fetching Dukascopy bars",
                args.symbol,
                tf,
                start.isoformat(timespec="seconds"),
                now.isoformat(timespec="seconds"),
            )

            fallback_reason = None
            dukascopy_records = []
            try:
                dukascopy_records = list(
                    fetch_bars(
                        args.symbol,
                        tf,
                        start=start,
                        end=now,
                    )
                )
            except Exception as exc:
                fallback_reason = f"fetch error: {exc}"

            freshness_threshold = args.dukascopy_freshness_threshold_minutes
            if fallback_reason is None:
                if not dukascopy_records:
                    fallback_reason = "no rows returned"
                else:
                    last_record_ts = str(dukascopy_records[-1].get("timestamp", ""))
                    try:
                        parsed_last = datetime.fromisoformat(
                            last_record_ts.replace("Z", "+00:00")
                        )
                        if parsed_last.tzinfo is not None:
                            parsed_last = (
                                parsed_last.astimezone(timezone.utc)
                                .replace(tzinfo=None)
                            )
                    except Exception:
                        parsed_last = None

                    if parsed_last is None:
                        fallback_reason = "could not parse last timestamp"
                    else:
                        if freshness_threshold and freshness_threshold > 0:
                            max_age = timedelta(minutes=freshness_threshold)
                            if now - parsed_last > max_age:
                                fallback_reason = (
                                    "stale data: "
                                    f"last_ts={parsed_last.isoformat(timespec='seconds')}"
                                )

            records_to_ingest = dukascopy_records
            source_name = "dukascopy"

            if fallback_reason is not None:
                print(
                    "[wf] Dukascopy unavailable, switching to yfinance fallback:",
                    fallback_reason,
                )
                try:
                    from scripts import yfinance_fetch as yfinance_module
                except Exception as exc:  # pragma: no cover - optional dependency
                    print(f"[wf] yfinance fallback unavailable: {exc}")
                    return 1

                fallback_window_days = 7
                fallback_start = now - timedelta(days=fallback_window_days)
                fetch_symbol = yfinance_module.resolve_ticker(symbol_upper)
                print(
                    "[wf] fetching yfinance bars",
                    fetch_symbol,
                    f"(fallback for {symbol_upper})",
                    tf,
                    fallback_start.isoformat(timespec="seconds"),
                    now.isoformat(timespec="seconds"),
                )

                try:
                    records_to_ingest = list(
                        yfinance_module.fetch_bars(
                            args.symbol,
                            tf,
                            start=fallback_start,
                            end=now,
                        )
                    )
                except Exception as exc:
                    print(f"[wf] yfinance fallback failed: {exc}")
                    return 1

                if not records_to_ingest:
                    print("[wf] yfinance fallback returned no rows")
                    return 1

                source_name = "yfinance"

            try:
                result = ingest_records(
                    records_to_ingest,
                    symbol=symbol_upper,
                    tf=tf,
                    snapshot_path=snapshot_path,
                    raw_path=raw_path,
                    validated_path=validated_path,
                    features_path=features_path,
                    source_name=source_name,
                )
            except Exception as exc:
                print(f"[wf] ingestion failed: {exc}")
                return 1

            print(
                f"[wf] {source_name}_ingest",
                f"rows={result['rows_validated']}",
                f"last_ts={result['last_ts_now']}",
            )
        elif args.use_yfinance:
            try:
                from scripts.yfinance_fetch import fetch_bars, resolve_ticker
                from scripts.pull_prices import ingest_records, get_last_processed_ts
            except RuntimeError as exc:
                print(f"[wf] yfinance ingestion unavailable: {exc}")
                return 1
            except Exception as exc:  # pragma: no cover - import error
                print(f"[wf] yfinance ingestion failed to initialize: {exc}")
                return 1

            snapshot_path = ROOT / "ops/runtime_snapshot.json"
            tf = "5m"
            symbol_upper = args.symbol
            validated_path = ROOT / "validated" / symbol_upper / f"{tf}.csv"
            raw_path = ROOT / "raw" / symbol_upper / f"{tf}.csv"
            features_path = ROOT / "features" / symbol_upper / f"{tf}.csv"

            last_ts = get_last_processed_ts(
                symbol_upper,
                tf,
                snapshot_path=snapshot_path,
                validated_path=validated_path,
            )
            lookback = max(5, args.yfinance_lookback_minutes)
            now = datetime.utcnow()
            if last_ts is not None:
                start = last_ts - timedelta(minutes=lookback)
            else:
                start = now - timedelta(minutes=lookback)

            fetch_symbol = resolve_ticker(symbol_upper)
            print(
                "[wf] fetching yfinance bars",
                fetch_symbol,
                f"(source {symbol_upper})",
                tf,
                start.isoformat(timespec="seconds"),
                now.isoformat(timespec="seconds"),
            )

            try:
                records = fetch_bars(
                    args.symbol,
                    tf,
                    start=start,
                    end=now,
                )
                result = ingest_records(
                    records,
                    symbol=symbol_upper,
                    tf=tf,
                    snapshot_path=snapshot_path,
                    raw_path=raw_path,
                    validated_path=validated_path,
                    features_path=features_path,
                    source_name="yfinance",
                )
            except Exception as exc:
                print(f"[wf] yfinance ingestion failed: {exc}")
                return 1

            print(
                "[wf] yfinance_ingest",
                f"rows={result['rows_validated']}",
                f"last_ts={result['last_ts_now']}",
            )
        elif args.use_api:
            try:
                from scripts.fetch_prices_api import fetch_prices
                from scripts.pull_prices import ingest_records, get_last_processed_ts
            except Exception as exc:  # pragma: no cover - import failure
                print(f"[wf] API ingestion unavailable: {exc}")
                return 1

            snapshot_path = ROOT / "ops/runtime_snapshot.json"
            tf = "5m"
            symbol_upper = args.symbol.upper()
            validated_path = ROOT / "validated" / symbol_upper / f"{tf}.csv"
            raw_path = ROOT / "raw" / symbol_upper / f"{tf}.csv"
            features_path = ROOT / "features" / symbol_upper / f"{tf}.csv"

            last_ts = get_last_processed_ts(
                symbol_upper,
                tf,
                snapshot_path=snapshot_path,
                validated_path=validated_path,
            )
            now = datetime.utcnow()
            lookback_default = args.api_lookback_minutes
            if lookback_default is None:
                try:
                    with Path(args.api_config).open(encoding="utf-8") as fh:
                        cfg = yaml.safe_load(fh) or {}
                    provider_name = args.api_provider or cfg.get("default_provider")
                    providers = cfg.get("providers", {})
                    provider_cfg = providers.get(provider_name) if provider_name else None
                    lookback_default = (
                        args.api_lookback_minutes
                        or (provider_cfg or {}).get("lookback_minutes")
                        or cfg.get("lookback_minutes")
                    )
                except Exception:
                    lookback_default = None
            lookback_minutes = max(5, int(lookback_default or 120))

            if last_ts is not None:
                start = last_ts - timedelta(minutes=lookback_minutes)
            else:
                start = now - timedelta(minutes=lookback_minutes)

            print(
                "[wf] fetching API bars",
                args.symbol,
                tf,
                start.isoformat(timespec="seconds"),
                now.isoformat(timespec="seconds"),
            )

            try:
                records = fetch_prices(
                    symbol_upper,
                    tf,
                    start=start,
                    end=now,
                    provider=args.api_provider,
                    config_path=args.api_config,
                    credentials_path=args.api_credentials,
                )
                result = ingest_records(
                    records,
                    symbol=symbol_upper,
                    tf=tf,
                    snapshot_path=snapshot_path,
                    raw_path=raw_path,
                    validated_path=validated_path,
                    features_path=features_path,
                    source_name="api",
                )
            except Exception as exc:
                print(f"[wf] API ingestion failed: {exc}")
                return 1

            print(
                "[wf] api_ingest",
                f"rows={result['rows_validated']}",
                f"last_ts={result['last_ts_now']}",
            )
        else:
            cmd = [
                sys.executable,
                str(ROOT / "scripts/pull_prices.py"),
                "--source",
                str(ROOT / "data/usdjpy_5m_2018-2024_utc.csv"),
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
