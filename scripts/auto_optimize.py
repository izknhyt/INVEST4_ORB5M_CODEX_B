#!/usr/bin/env python3
"""Run optimize_params.py and post summary via notifications."""
from __future__ import annotations
import argparse
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_optimize(argv, report_path: Path) -> dict:
    cmd = [sys.executable, str(ROOT / "scripts/optimize_params.py")] + argv
    if "--report" not in argv:
        cmd += ["--report", str(report_path)]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    if report_path.exists():
        return json.loads(report_path.read_text(encoding="utf-8"))
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip().startswith('{')]
    return json.loads(lines[-1]) if lines else {}


def send_notification(summary: dict, webhook: str | None):
    if not webhook:
        return
    payload = {
        "signal_id": f"optimize_{summary.get('symbol','unknown')}",
        "side": "BUY",
        "entry": 0.0,
        "tp": 0.0,
        "sl": 0.0,
        "trail": 0.0,
        "confidence": 0.0,
        "meta": summary,
    }
    cmd = [sys.executable, str(ROOT / "notifications/emit_signal.py"),
           "--signal-id", payload["signal_id"],
           "--side", payload["side"],
           "--entry", "0",
           "--tp", "0",
           "--sl", "0",
           "--confidence", "0",
           "--webhook-url", webhook,
           "--meta", json.dumps(summary, ensure_ascii=False),
           "--latency-log", str(ROOT / "ops/optimize_notify_latency.csv"),
           "--fallback-log", str(ROOT / "ops/optimize_notify.log")]
    subprocess.run(cmd, check=False)


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Run optimize_params and notify")
    p.add_argument("--opt-args", nargs=argparse.REMAINDER, default=[],
                   help="Arguments to pass to optimize_params.py")
    p.add_argument("--webhook", default=None, help="Notification webhook URL")
    p.add_argument("--report", default="reports/optimize_report.json")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    summary = run_optimize(args.opt_args, report_path)
    send_notification(summary, args.webhook)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
