"""CLI to assemble observability dashboard inputs."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from analysis.dashboard import (
    EVSnapshot,
    SlippageSnapshot,
    TurnoverSnapshot,
    load_ev_history,
    load_execution_slippage,
    load_state_slippage,
    load_turnover_metrics,
)


def _resolve_archive_dir(args: argparse.Namespace) -> Path:
    if args.archive_dir:
        return Path(args.archive_dir)
    base = Path(args.state_archive_root)
    return base / args.strategy / args.symbol / args.mode


def _serialize_ev_history(history: List[EVSnapshot]) -> List[Dict[str, object]]:
    return [item.to_dict() for item in history]


def _serialize_slippage(snapshots: List[SlippageSnapshot]) -> List[Dict[str, object]]:
    return [item.to_dict() for item in snapshots]


def _serialize_turnover(snapshots: List[TurnoverSnapshot]) -> List[Dict[str, object]]:
    return [item.to_dict() for item in snapshots]


def build_payload(args: argparse.Namespace) -> Dict[str, object]:
    archive_dir = _resolve_archive_dir(args)
    ev_history = load_ev_history(archive_dir, limit=args.ev_limit)
    state_slip = load_state_slippage(archive_dir, limit=args.slip_limit)

    execution_slip: List[SlippageSnapshot] = []
    telemetry_path = Path(args.portfolio_telemetry) if args.portfolio_telemetry else None
    if telemetry_path is not None and telemetry_path.exists():
        execution_slip = load_execution_slippage(telemetry_path)

    turnover = load_turnover_metrics(Path(args.runs_root), limit=args.turnover_limit)

    latest_ev = ev_history[-1] if ev_history else None

    payload: Dict[str, object] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "archive_dir": str(archive_dir),
            "runs_root": str(Path(args.runs_root)),
            "strategy": args.strategy,
            "symbol": args.symbol,
            "mode": args.mode,
        },
        "ev_history": _serialize_ev_history(ev_history),
        "slippage": {
            "state": _serialize_slippage(state_slip),
            "execution": _serialize_slippage(execution_slip),
        },
        "turnover": _serialize_turnover(turnover),
    }
    if telemetry_path is not None:
        payload["inputs"]["portfolio_telemetry"] = str(telemetry_path)
    if latest_ev is not None:
        payload["win_rate_lcb"] = {
            "latest": latest_ev.to_dict(),
        }
    return payload


def parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export observability dashboard data as JSON")
    parser.add_argument("--runs-root", default="runs", help="Root directory containing run outputs")
    parser.add_argument(
        "--state-archive-root",
        default="ops/state_archive",
        help="Root directory containing EV state archives",
    )
    parser.add_argument("--archive-dir", help="Explicit EV archive directory (overrides strategy/symbol/mode)")
    parser.add_argument("--strategy", default="day_orb_5m.DayORB5m", help="Strategy identifier for archive resolution")
    parser.add_argument("--symbol", default="USDJPY", help="Symbol for archive resolution")
    parser.add_argument("--mode", default="conservative", help="Mode for archive resolution")
    parser.add_argument("--portfolio-telemetry", help="Path to router telemetry JSON for execution slippage")
    parser.add_argument("--ev-limit", type=int, default=120, help="Maximum EV snapshots to include (None for all)")
    parser.add_argument("--slip-limit", type=int, default=60, help="Maximum slippage snapshots to include (None for all)")
    parser.add_argument("--turnover-limit", type=int, default=50, help="Maximum turnover rows to include (None for all)")
    parser.add_argument("--out-json", required=True, help="Destination JSON path")
    parser.add_argument("--indent", type=int, default=2, help="Indent level for JSON output")
    return parser.parse_args(argv)


def main(argv: List[str] | None = None) -> int:
    args = parse_args(argv)
    payload = build_payload(args)
    out_path = Path(args.out_json)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=args.indent)
    print(json.dumps({"out_json": str(out_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
