#!/usr/bin/env python3
"""Replay newly ingested bars and refresh state.json on demand."""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import csv
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.runner import BacktestRunner
from scripts.config_utils import build_runner_config
from scripts.pull_prices import _parse_ts as _parse_ingest_ts


SNAPSHOT_PATH = Path("ops/runtime_snapshot.json")
DEFAULT_STATE = Path("runs/active/state.json")


def _load_snapshot(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with path.open() as f:
            return json.load(f)
    except Exception:
        return {}


def _save_snapshot(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _parse_timestamp(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return _parse_ingest_ts(value)
    except Exception:
        return None


def _format_timestamp(ts: datetime) -> str:
    return ts.replace(tzinfo=None).isoformat()


def _get_last_state_ts(snapshot: dict, key: str) -> Optional[datetime]:
    section = snapshot.get("state_update", {})
    ts_str = section.get(key)
    return _parse_timestamp(ts_str)


def _set_last_state_ts(snapshot: dict, key: str, ts: datetime) -> dict:
    section = snapshot.setdefault("state_update", {})
    section[key] = ts.isoformat()
    return snapshot


def _prune_archives(archive_dir: Path, keep: int = 5) -> List[Path]:
    files = sorted(
        [p for p in archive_dir.glob("*_state.json") if p.is_file()]
    )
    if keep <= 0:
        return []
    to_remove = files[:-keep]
    for path in to_remove:
        try:
            path.unlink()
        except OSError:
            pass
    return to_remove


def _run_aggregate_ev(archive_root: Path, strategy_key: str, symbol: str, mode: str) -> int:
    script_path = ROOT / "scripts" / "aggregate_ev.py"
    if not script_path.exists():
        return 0
    cmd = [
        sys.executable,
        str(script_path),
        "--archive",
        str(archive_root),
        "--strategy",
        strategy_key,
        "--symbol",
        symbol,
        "--mode",
        mode,
    ]
    try:
        completed = subprocess.run(cmd, check=False)
        return completed.returncode
    except Exception:
        return 1


def _parse_row(row: Dict[str, str]) -> Dict[str, Any]:
    return {
        "timestamp": row["timestamp"],
        "symbol": row.get("symbol", ""),
        "tf": row.get("tf", "5m"),
        "o": float(row["o"]),
        "h": float(row["h"]),
        "l": float(row["l"]),
        "c": float(row["c"]),
        "v": float(row.get("v", 0) or 0.0),
        "spread": float(row.get("spread", 0) or 0.0),
    }


def _iter_new_bars(path: Path, since: Optional[datetime]) -> Iterable[Dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts_raw = row.get("timestamp")
            if ts_raw is None:
                continue
            stamp = _parse_timestamp(ts_raw)
            if since is not None and stamp is not None and stamp <= since:
                continue
            if stamp is not None:
                row["timestamp"] = _format_timestamp(stamp)
            try:
                yield _parse_row(row)
            except (ValueError, KeyError):
                continue


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Update strategy state from newly ingested bars")
    parser.add_argument("--bars", default=None, help="Input bars CSV (default: validated/<symbol>/5m.csv)")
    parser.add_argument("--symbol", default="USDJPY")
    parser.add_argument("--mode", default="conservative", choices=["conservative", "bridge"])
    parser.add_argument("--equity", type=float, default=100_000.0)
    parser.add_argument("--state-in", default=None, help="Existing state file to load (default: state-out if present)")
    parser.add_argument("--state-out", default=str(DEFAULT_STATE), help="Where to write the refreshed state.json")
    parser.add_argument("--snapshot", default=str(SNAPSHOT_PATH))
    parser.add_argument("--archive-dir", default="ops/state_archive", help="Directory for timestamped state snapshots")
    # Optional overrides for RunnerConfig (mirrors run_sim)
    parser.add_argument("--threshold-lcb", type=float, default=None)
    parser.add_argument("--min-or-atr", type=float, default=None)
    parser.add_argument("--rv-cuts", default=None)
    parser.add_argument("--allow-low-rv", action="store_true")
    parser.add_argument("--allowed-sessions", default="LDN,NY")
    parser.add_argument("--or-n", type=int, default=None)
    parser.add_argument("--k-tp", type=float, default=None)
    parser.add_argument("--k-sl", type=float, default=None)
    parser.add_argument("--k-tr", type=float, default=None)
    parser.add_argument("--warmup", type=int, default=None)
    parser.add_argument("--prior-alpha", type=float, default=None)
    parser.add_argument("--prior-beta", type=float, default=None)
    parser.add_argument("--include-expected-slip", action="store_true")
    parser.add_argument("--ev-mode", choices=["lcb", "off", "mean"], default=None)
    parser.add_argument("--size-floor", type=float, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json-out", default=None, help="Optional metrics JSON path")
    parser.add_argument("--chunk-size", type=int, default=20000, help="Number of bars per replay chunk (default 20000)")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.bars:
        bars_path = Path(args.bars)
    else:
        bars_path = Path("validated") / args.symbol / "5m.csv"
    if not bars_path.exists():
        print(json.dumps({"error": "bars_not_found", "path": str(bars_path)}))
        return 1

    snapshot_path = Path(args.snapshot)
    snapshot = _load_snapshot(snapshot_path)
    state_key = f"{args.symbol}_{args.mode}"
    last_state_ts = _get_last_state_ts(snapshot, state_key)

    rcfg = build_runner_config(args)
    runner = BacktestRunner(equity=args.equity, symbol=args.symbol, runner_cfg=rcfg)

    state_in = Path(args.state_in) if args.state_in else Path(args.state_out)
    if state_in and state_in.exists():
        try:
            runner.load_state_file(str(state_in))
        except Exception:
            pass

    chunk_size = max(1, int(args.chunk_size))

    total_processed = 0
    latest_ts: Optional[datetime] = None
    metrics = None

    new_bar_iter = _iter_new_bars(bars_path, last_state_ts)

    chunk: List[Dict[str, Any]] = []
    for bar in new_bar_iter:
        chunk.append(bar)
        ts_value = bar.get("timestamp")
        parsed_ts = _parse_timestamp(ts_value) if isinstance(ts_value, str) else None
        if parsed_ts is not None:
            latest_ts = parsed_ts
        if len(chunk) >= chunk_size:
            metrics = runner.run_partial(chunk, mode=args.mode)
            total_processed += len(chunk)
            chunk = []
    if chunk:
        metrics = runner.run_partial(chunk, mode=args.mode)
        total_processed += len(chunk)
        ts_value = chunk[-1].get("timestamp")
        parsed_ts = _parse_timestamp(ts_value) if isinstance(ts_value, str) else None
        if parsed_ts is not None:
            latest_ts = parsed_ts

    if total_processed == 0:
        print(json.dumps({
            "message": "no_new_bars",
            "symbol": args.symbol,
            "mode": args.mode,
            "last_ts": last_state_ts.isoformat() if last_state_ts else None,
        }, ensure_ascii=False))
        return 0

    if metrics is None:
        metrics = runner.metrics
    new_state = runner.export_state()

    state_out_path = Path(args.state_out)
    state_out_path.parent.mkdir(parents=True, exist_ok=True)
    if not args.dry_run:
        with state_out_path.open("w") as f:
            json.dump(new_state, f, ensure_ascii=False, indent=2)

        strategy_module = runner.strategy_cls.__module__
        strategy_name = getattr(runner.strategy_cls, "__name__", "strategy")
        strategy_key = f"{strategy_module}.{strategy_name}"

        archive_root = Path(args.archive_dir)
        archive_dir = archive_root / strategy_key / args.symbol / args.mode
        archive_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        archive_file = archive_dir / f"{stamp}_state.json"
        with archive_file.open("w") as f:
            json.dump(new_state, f, ensure_ascii=False, indent=2)

        pruned = _prune_archives(archive_dir, keep=5)
        agg_rc = _run_aggregate_ev(archive_root, strategy_key, args.symbol, args.mode)

        if latest_ts:
            snapshot = _set_last_state_ts(snapshot, state_key, latest_ts)
            _save_snapshot(snapshot_path, snapshot)

    result = metrics.as_dict()
    result.update({
        "bars_processed": total_processed,
        "state_out": str(state_out_path),
    })
    if not args.dry_run:
        result.update({
            "strategy_key": strategy_key,
            "archive_dir": str(archive_dir),
            "ev_archive_latest": str(archive_file),
            "ev_archives_pruned": [str(p) for p in pruned],
            "aggregate_ev_rc": agg_rc,
        })
    print(json.dumps(result, ensure_ascii=False))

    if args.json_out:
        with Path(args.json_out).open("w") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
