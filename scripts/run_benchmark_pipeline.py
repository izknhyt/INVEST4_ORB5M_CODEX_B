#!/usr/bin/env python3
"""Orchestrate benchmark runs followed by summary aggregation."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_PATH = ROOT / "ops" / "runtime_snapshot.json"
MANDATORY_WINDOWS = (365, 180, 90)


def _load_snapshot(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open() as f:
            return json.load(f)
    except Exception:
        return {}


def _save_snapshot_atomic(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix="snapshot_", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w") as tmp_file:
            json.dump(data, tmp_file, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    finally:
        try:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
        except OSError:
            pass


def _run_subprocess(cmd: List[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=False, capture_output=True, text=True)


def _parse_json_output(name: str, output: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    try:
        payload = json.loads(output) if output else None
    except json.JSONDecodeError as exc:
        return None, f"{name} produced invalid JSON: {exc}"
    if not isinstance(payload, dict):
        return None, f"{name} returned non-object JSON payload"
    return payload, None


def _ensure_mandatory_windows(windows: Iterable[int]) -> Optional[str]:
    window_set: set[int] = set()
    for value in windows:
        try:
            window_set.add(int(value))
        except (TypeError, ValueError):
            continue
    missing = [w for w in MANDATORY_WINDOWS if w not in window_set]
    if missing:
        return f"missing mandatory rolling windows: {','.join(str(w) for w in missing)}"
    return None


def _normalize_windows_arg(raw: str) -> str:
    parsed: List[int] = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            value = int(chunk)
        except ValueError:
            continue
        if value not in parsed:
            parsed.append(value)

    normalized: List[int] = list(MANDATORY_WINDOWS)
    for value in parsed:
        if value not in normalized:
            normalized.append(value)
    return ",".join(str(value) for value in normalized)


def _validate_rolling_outputs(rolling: List[Dict[str, Any]]) -> Optional[str]:
    if not rolling:
        return "benchmark payload did not include rolling metrics"

    error = _ensure_mandatory_windows(entry.get("window") for entry in rolling if "window" in entry)
    if error:
        return error

    for entry in rolling:
        window = entry.get("window")
        if not isinstance(window, int):
            return "rolling entry missing integer window"
        if entry.get("skipped"):
            return f"rolling window {window} was skipped"
        path_value = entry.get("path")
        if not isinstance(path_value, str):
            return f"rolling window {window} missing path"
        path = Path(path_value)
        if not path.exists():
            return f"rolling window {window} output not found: {path}"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # pragma: no cover - defensive
            return f"failed to read rolling window {window} output {path}: {exc}"
        for key in ("sharpe", "max_drawdown"):
            if data.get(key) is None:
                return f"rolling window {window} missing {key}"
        parent = path.parent
        if parent.name != str(window) or parent.parent.name != "rolling":
            return f"rolling window {window} output stored outside reports/rolling/{window}"
    return None


def _ensure_summary_written(summary_path: Path) -> Optional[str]:
    if not summary_path.exists():
        return f"benchmark summary was not written to {summary_path}"
    try:
        json.loads(summary_path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - defensive
        return f"benchmark summary at {summary_path} is not valid JSON: {exc}"
    return None


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run benchmark pipeline (baseline + rolling + summary)")
    parser.add_argument("--bars", default=None, help="CSV path (default: validated/<symbol>/5m.csv)")
    parser.add_argument("--symbol", default="USDJPY")
    parser.add_argument("--mode", default="conservative", choices=["conservative", "bridge"])
    parser.add_argument("--equity", type=float, default=100_000.0)
    parser.add_argument("--windows", default="365,180,90", help="Rolling windows in days (comma separated)")
    parser.add_argument("--reports-dir", default="reports", help="Where to store metrics JSON")
    parser.add_argument("--runs-dir", default="runs", help="Directory for run artifacts")
    parser.add_argument("--snapshot", default=str(SNAPSHOT_PATH))
    parser.add_argument("--summary-json", default="reports/benchmark_summary.json")
    parser.add_argument("--summary-plot", default="reports/benchmark_summary.png")
    parser.add_argument("--min-sharpe", type=float, default=None)
    parser.add_argument("--max-drawdown", type=float, default=None)
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
    parser.add_argument("--webhook", default=None, help="Webhook URL(s) for alerts (comma separated)")
    parser.add_argument("--dry-run", action="store_true", help="Skip writes and subprocess execution")
    return parser.parse_args(argv)


def _build_benchmark_cmd(args: argparse.Namespace, snapshot_path: Path) -> List[str]:
    bars_path = args.bars or str(ROOT / f"validated/{args.symbol}/5m.csv")
    windows_arg = _normalize_windows_arg(args.windows)
    cmd = [
        sys.executable,
        str(ROOT / "scripts/run_benchmark_runs.py"),
        "--bars",
        str(bars_path),
        "--symbol",
        args.symbol,
        "--mode",
        args.mode,
        "--equity",
        str(args.equity),
        "--windows",
        windows_arg,
        "--reports-dir",
        str(args.reports_dir),
        "--runs-dir",
        str(args.runs_dir),
        "--snapshot",
        str(snapshot_path),
    ]
    if args.alert_pips is not None:
        cmd += ["--alert-pips", str(args.alert_pips)]
    if args.alert_winrate is not None:
        cmd += ["--alert-winrate", str(args.alert_winrate)]
    if args.webhook:
        cmd += ["--webhook", args.webhook]
    return cmd


def _build_summary_cmd(args: argparse.Namespace) -> List[str]:
    windows_arg = _normalize_windows_arg(args.windows)
    cmd = [
        sys.executable,
        str(ROOT / "scripts/report_benchmark_summary.py"),
        "--symbol",
        args.symbol,
        "--mode",
        args.mode,
        "--reports-dir",
        str(args.reports_dir),
        "--windows",
        windows_arg,
        "--json-out",
        str(args.summary_json),
    ]
    if args.summary_plot:
        cmd += ["--plot-out", str(args.summary_plot)]
    if args.min_sharpe is not None:
        cmd += ["--min-sharpe", str(args.min_sharpe)]
    if args.max_drawdown is not None:
        cmd += ["--max-drawdown", str(args.max_drawdown)]
    if args.webhook:
        cmd += ["--webhook", args.webhook]
    return cmd


def _update_snapshot(snapshot_path: Path, key: str, benchmark_payload: Dict[str, Any], summary_payload: Dict[str, Any]) -> None:
    snapshot = _load_snapshot(snapshot_path)
    benchmarks_section = snapshot.setdefault("benchmarks", {})
    latest_ts = benchmark_payload.get("latest_ts")
    if isinstance(latest_ts, str):
        benchmarks_section[key] = latest_ts
    pipeline_section = snapshot.setdefault("benchmark_pipeline", {})
    pipeline_section[key] = {
        "latest_ts": latest_ts,
        "summary_generated_at": summary_payload.get("generated_at"),
        "warnings": summary_payload.get("warnings", []),
    }
    _save_snapshot_atomic(snapshot_path, snapshot)


def main(argv=None) -> int:
    args = parse_args(argv)

    if args.dry_run:
        payload = {
            "message": "dry_run",
            "pipeline": {
                "symbol": args.symbol,
                "mode": args.mode,
                "windows": args.windows,
            },
        }
        print(json.dumps(payload, ensure_ascii=False))
        return 0

    fd, tmp_name = tempfile.mkstemp(prefix="benchmark_", suffix=".json")
    os.close(fd)
    temp_snapshot = Path(tmp_name)
    try:
        benchmark_cmd = _build_benchmark_cmd(args, temp_snapshot)
        benchmark_proc = _run_subprocess(benchmark_cmd)
        if benchmark_proc.stderr:
            print(benchmark_proc.stderr, file=sys.stderr, end="")
        if benchmark_proc.returncode != 0:
            return benchmark_proc.returncode

        benchmark_payload, error = _parse_json_output("run_benchmark_runs", benchmark_proc.stdout)
        if error:
            print(error, file=sys.stderr)
            return 1

        validation_error = _validate_rolling_outputs(benchmark_payload.get("rolling", []))
        if validation_error:
            print(validation_error, file=sys.stderr)
            return 1

        summary_cmd = _build_summary_cmd(args)
        summary_proc = _run_subprocess(summary_cmd)
        if summary_proc.stderr:
            print(summary_proc.stderr, file=sys.stderr, end="")
        if summary_proc.returncode != 0:
            return summary_proc.returncode

        summary_payload, error = _parse_json_output("report_benchmark_summary", summary_proc.stdout)
        if error:
            print(error, file=sys.stderr)
            return 1

        summary_path = Path(args.summary_json)
        summary_error = _ensure_summary_written(summary_path)
        if summary_error:
            print(summary_error, file=sys.stderr)
            return 1

        snapshot_path = Path(args.snapshot)
        key = f"{args.symbol}_{args.mode}"
        _update_snapshot(snapshot_path, key, benchmark_payload, summary_payload)

        combined = {
            "benchmark_runs": benchmark_payload,
            "summary": summary_payload,
        }
        print(json.dumps(combined, ensure_ascii=False))
        return 0
    finally:
        try:
            temp_snapshot.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
