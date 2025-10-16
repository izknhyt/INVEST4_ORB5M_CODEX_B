#!/usr/bin/env python3
"""Replay newly ingested bars and refresh state.json on demand."""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import csv
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.runner import BacktestRunner
from notifications import emit_signal
from scripts._time_utils import utcnow_aware
from scripts.config_utils import build_runner_config
from scripts.pull_prices import _parse_ts as _parse_ingest_ts


SNAPSHOT_PATH = Path("ops/runtime_snapshot.json")
DEFAULT_STATE = Path("runs/active/state.json")
DEFAULT_OVERRIDE_PATH = Path("ops/state_archive/auto_adjust_override.json")


def _flatten_numeric(data: Any, prefix: Tuple[str, ...] = ()) -> Dict[str, float]:
    values: Dict[str, float] = {}
    if isinstance(data, dict):
        for key in sorted(data.keys()):
            values.update(_flatten_numeric(data[key], prefix + (str(key),)))
    elif isinstance(data, (int, float)) and not isinstance(data, bool):
        values[".".join(prefix)] = float(data)
    return values


def _build_state_diff(previous: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, Any]:
    prev_numeric = _flatten_numeric(previous)
    curr_numeric = _flatten_numeric(current)
    updated: List[Dict[str, Any]] = []
    for key in sorted(set(prev_numeric) | set(curr_numeric)):
        if key not in prev_numeric or key not in curr_numeric:
            continue
        old_val = prev_numeric[key]
        new_val = curr_numeric[key]
        if math.isclose(old_val, new_val, rel_tol=0.0, abs_tol=0.0):
            continue
        updated.append({
            "path": key,
            "previous": old_val,
            "current": new_val,
            "delta": new_val - old_val,
            "abs_delta": abs(new_val - old_val),
        })
    updated.sort(key=lambda item: item["abs_delta"], reverse=True)
    added = sorted(set(curr_numeric) - set(prev_numeric))
    removed = sorted(set(prev_numeric) - set(curr_numeric))
    return {"updated": updated, "added": added, "removed": removed}


def _build_decision_reasons(args, override_status: Dict[str, Any], anomalies: List[Dict[str, Any]], applied: bool) -> List[str]:
    reasons: List[str] = []
    if args.dry_run:
        reasons.append("dry_run")
    if not override_status.get("enabled", True):
        reasons.append("override_disabled")
    if args.simulate_live and anomalies:
        seen = set()
        for anomaly in anomalies:
            label = anomaly.get("type", "anomaly")
            key = f"anomaly:{label}"
            if key not in seen:
                reasons.append(key)
                seen.add(key)
    if applied and not reasons:
        reasons.append("conditions_met")
    elif not applied and not reasons:
        reasons.append("blocked")
    return reasons


def _compute_var(trade_returns: Iterable[float], percentile: float = 5.0) -> float:
    data = [float(v) for v in trade_returns]
    if not data:
        return 0.0
    ordered = sorted(data)
    if not ordered:
        return 0.0
    idx = int(math.floor(max(0.0, min(100.0, percentile)) / 100.0 * (len(ordered) - 1)))
    value = ordered[idx]
    return float(max(0.0, -value))


def _compute_liquidity(records: Iterable[Dict[str, Any]]) -> float:
    usage = 0.0
    for record in records:
        if not isinstance(record, dict):
            continue
        qty = record.get("qty")
        if qty is None:
            continue
        try:
            usage += abs(float(qty))
        except (TypeError, ValueError):
            continue
    return usage


def _build_paper_validation_summary(
    *,
    decision_status: str,
    anomalies: Sequence[Mapping[str, Any]],
    dry_run: bool,
    total_processed: int,
    risk_summary: Mapping[str, Any],
) -> Dict[str, Any]:
    """Summarise pseudo-live guardrail evaluation for downstream reports."""

    summary: Dict[str, Any] = {
        "status": "go",
        "decision": decision_status,
        "bars_processed": total_processed,
        "anomaly_count": len(anomalies),
        "anomaly_types": [
            str(item.get("type"))
            for item in anomalies
            if isinstance(item, Mapping) and item.get("type")
        ],
        "risk": risk_summary,
        "reasons": [],
    }

    reasons: List[str] = []
    if decision_status != "applied":
        summary["status"] = "no-go"
        reasons.append(f"decision:{decision_status}")
    if anomalies:
        summary["status"] = "no-go"
        reasons.append("anomalies_detected")
    if dry_run:
        reasons.append("dry_run")

    deduped: List[str] = []
    for reason in reasons:
        if reason and reason not in deduped:
            deduped.append(reason)
    summary["reasons"] = deduped
    return summary


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open() as f:
            return json.load(f)
    except Exception:
        return {}


def _write_override(path: Path, status: str, reason: Optional[str], dry_run: bool) -> Dict[str, Any]:
    payload = {
        "status": status,
        "reason": reason,
        "updated_at": utcnow_aware(dt_cls=datetime).isoformat(),
    }
    if dry_run:
        return {"preview": payload, "path": str(path)}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return {"result": payload, "path": str(path)}


def _handle_override_action(args) -> Optional[int]:
    if args.override_action == "none":
        return None
    override_path = Path(args.override_path)
    if args.override_action == "status":
        data = _load_json(override_path)
        output = {
            "override_path": str(override_path),
            "status": data.get("status", "enabled"),
            "reason": data.get("reason"),
            "updated_at": data.get("updated_at"),
        }
        print(json.dumps(output, ensure_ascii=False))
        return 0
    if args.override_action in {"disable", "enable"}:
        status = "disabled" if args.override_action == "disable" else "enabled"
        if args.override_action == "disable" and not args.override_reason:
            print(json.dumps({
                "error": "override_reason_required",
                "message": "--override-reason is required when disabling auto adjustments",
            }, ensure_ascii=False))
            return 2
        record = _write_override(override_path, status, args.override_reason, args.dry_run)
        record.update({
            "override_action": args.override_action,
            "dry_run": bool(args.dry_run),
        })
        print(json.dumps(record, ensure_ascii=False))
        return 0
    return 1


def _load_override_status(path: Path) -> Dict[str, Any]:
    data = _load_json(path)
    status = data.get("status", "enabled")
    return {
        "status": status,
        "reason": data.get("reason"),
        "updated_at": data.get("updated_at"),
        "path": str(path),
        "enabled": status != "disabled",
    }


def _send_alert(args, simulate_live: bool, dry_run: bool, anomalies: List[Dict[str, Any]]) -> Dict[str, Any]:
    timestamp = utcnow_aware(dt_cls=datetime).isoformat()
    urls = emit_signal.resolve_webhook_urls(args.alert_webhook)
    fallback_extra: Optional[Dict[str, Any]] = None
    if not urls:
        fallback_extra = {
            "env_var": "SIGNAL_WEBHOOK_URLS",
            "env_present": bool(os.getenv("SIGNAL_WEBHOOK_URLS")),
            "cli_override": bool(args.alert_webhook),
            "message": "No webhook URLs configured for state_update_rollback",
        }
    payload = emit_signal.SignalPayload(
        signal_id="state_update_rollback",
        timestamp_utc=timestamp,
        side="SELL",
        entry=0.0,
        tp=0.0,
        sl=0.0,
        trail=0.0,
        confidence=0.0,
        meta={
            "simulate_live": simulate_live,
            "dry_run": dry_run,
            "anomalies": anomalies,
        },
    )

    record = {
        "mode": args.alert_mode,
        "urls": urls,
        "timestamp": timestamp,
        "dry_run": dry_run,
    }

    if args.alert_mode == "disable":
        record["status"] = "skipped"
        record["detail"] = "alert_mode_disable"
        return record

    should_send = args.alert_mode == "force" or (simulate_live and anomalies)
    if not should_send:
        record["status"] = "skipped"
        record["detail"] = "no_trigger"
        return record

    if dry_run or not urls:
        record["status"] = "preview"
        record_detail = "dry_run" if dry_run else "no_webhook_configured"
        record["detail"] = record_detail
        record["payload"] = json.loads(payload.to_json())
        if not dry_run and not urls:
            emit_signal.log_latency(args.alert_latency_log, payload.signal_id, timestamp, False, record_detail)
            emit_signal.log_fallback(
                args.alert_fallback_log,
                payload,
                record_detail,
                extra=fallback_extra,
            )
        return record

    success = False
    detail = ""
    for url in urls:
        ok, detail = emit_signal.send_webhook(url, payload)
        if ok:
            success = True
            break

    emit_signal.log_latency(args.alert_latency_log, payload.signal_id, timestamp, success, detail)
    if not success:
        emit_signal.log_fallback(args.alert_fallback_log, payload, detail, extra=fallback_extra)

    record["status"] = "sent" if success else "failed"
    record["detail"] = detail
    return record


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
    parser.add_argument("--simulate-live", action="store_true", help="Enable pseudo-live guardrails and anomaly handling")
    parser.add_argument("--max-delta", type=float, default=None, help="Maximum absolute delta per state field")
    parser.add_argument("--var-cap", type=float, default=None, help="Maximum allowed Value-at-Risk (5th percentile)")
    parser.add_argument("--liquidity-cap", type=float, default=None, help="Maximum total absolute quantity for new trades")
    parser.add_argument(
        "--override-action",
        choices=["none", "disable", "enable", "status"],
        default="none",
        help="Manage auto-adjust override state before updating",
    )
    parser.add_argument("--override-reason", default=None, help="Reason for override enable/disable actions")
    parser.add_argument("--override-path", default=str(DEFAULT_OVERRIDE_PATH), help="Override flag JSON path")
    parser.add_argument(
        "--alert-mode",
        choices=["auto", "disable", "force"],
        default="auto",
        help="Control alert delivery (auto=on anomaly, disable=never, force=always)",
    )
    parser.add_argument("--alert-webhook", default=None, help="Override webhook destinations for alerts")
    parser.add_argument("--alert-latency-log", default="ops/state_alert_latency.csv")
    parser.add_argument("--alert-fallback-log", default="ops/state_alerts.log")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    override_exit = _handle_override_action(args)
    if override_exit is not None:
        return override_exit

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

    override_status = _load_override_status(Path(args.override_path))

    rcfg = build_runner_config(args)
    runner = BacktestRunner(equity=args.equity, symbol=args.symbol, runner_cfg=rcfg)

    state_in = Path(args.state_in) if args.state_in else Path(args.state_out)
    previous_state: Dict[str, Any] = {}
    if state_in and state_in.exists():
        try:
            runner.load_state_file(str(state_in))
            previous_state = _load_json(state_in)
        except Exception:
            previous_state = {}

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

    state_diff = _build_state_diff(previous_state, new_state)
    risk_summary = {
        "var": float(_compute_var(getattr(metrics, "trade_returns", []) if metrics else [])),
        "liquidity_usage": float(_compute_liquidity(getattr(metrics, "records", []) if metrics else [])),
    }

    anomalies: List[Dict[str, Any]] = []
    if args.simulate_live:
        if args.max_delta is not None:
            violations = [item for item in state_diff["updated"] if item["abs_delta"] > args.max_delta]
            if violations:
                anomalies.append({
                    "type": "max_delta_exceeded",
                    "max_delta": args.max_delta,
                    "violations": violations,
                })
        if args.var_cap is not None and risk_summary["var"] > args.var_cap:
            anomalies.append({
                "type": "var_cap_exceeded",
                "var": risk_summary["var"],
                "cap": args.var_cap,
            })
        if args.liquidity_cap is not None and risk_summary["liquidity_usage"] > args.liquidity_cap:
            anomalies.append({
                "type": "liquidity_cap_exceeded",
                "liquidity_usage": risk_summary["liquidity_usage"],
                "cap": args.liquidity_cap,
            })

    strategy_module = runner.strategy_cls.__module__
    strategy_name = getattr(runner.strategy_cls, "__name__", "strategy")
    strategy_key = f"{strategy_module}.{strategy_name}"

    archive_root = Path(args.archive_dir)
    archive_dir = archive_root / strategy_key / args.symbol / args.mode
    stamp = utcnow_aware(dt_cls=datetime).strftime("%Y%m%d_%H%M%S")
    archive_file = archive_dir / f"{stamp}_state.json"
    diff_file = archive_dir / f"{stamp}_diff.json"

    state_out_path = Path(args.state_out)
    agg_rc: Optional[int] = None
    pruned: List[Path] = []

    should_apply = (
        not args.dry_run
        and override_status["enabled"]
        and (not args.simulate_live or not anomalies)
    )

    decision_status = "applied" if should_apply else ("preview" if args.dry_run else "blocked")
    decision_reasons = _build_decision_reasons(args, override_status, anomalies, should_apply)

    archive_meta: Dict[str, Any] = {}

    if should_apply:
        state_out_path.parent.mkdir(parents=True, exist_ok=True)
        with state_out_path.open("w") as f:
            json.dump(new_state, f, ensure_ascii=False, indent=2)

        archive_dir.mkdir(parents=True, exist_ok=True)
        with archive_file.open("w") as f:
            json.dump(new_state, f, ensure_ascii=False, indent=2)

        pruned = _prune_archives(archive_dir, keep=5)
        agg_rc = _run_aggregate_ev(archive_root, strategy_key, args.symbol, args.mode)

        if latest_ts:
            snapshot = _set_last_state_ts(snapshot, state_key, latest_ts)
            _save_snapshot(snapshot_path, snapshot)

        diff_payload = {
            "status": decision_status,
            "strategy_key": strategy_key,
            "symbol": args.symbol,
            "mode": args.mode,
            "bars_processed": total_processed,
            "diff": state_diff,
            "risk": risk_summary,
            "anomalies": anomalies,
            "reason": decision_reasons,
        }
        archive_dir.mkdir(parents=True, exist_ok=True)
        with diff_file.open("w") as f:
            json.dump(diff_payload, f, ensure_ascii=False, indent=2)

        archive_meta = {
            "strategy_key": strategy_key,
            "archive_dir": str(archive_dir),
            "ev_archive_latest": str(archive_file),
            "ev_archives_pruned": [str(p) for p in pruned],
            "aggregate_ev_rc": agg_rc,
            "diff_path": str(diff_file),
            "diff_status": decision_status,
            "diff_reason": decision_reasons,
        }
    else:
        legacy_reason: List[str] = []
        if args.dry_run:
            legacy_reason.append("dry_run")
        if not override_status["enabled"]:
            legacy_reason.append("override_disabled")
        if args.simulate_live and anomalies:
            legacy_reason.append("anomalies_present")
        diff_payload = {
            "status": decision_status,
            "strategy_key": strategy_key,
            "symbol": args.symbol,
            "mode": args.mode,
            "bars_processed": total_processed,
            "diff": state_diff,
            "risk": risk_summary,
            "anomalies": anomalies,
            "reason": decision_reasons,
        }
        if not args.dry_run:
            archive_dir.mkdir(parents=True, exist_ok=True)
            with diff_file.open("w") as f:
                json.dump(diff_payload, f, ensure_ascii=False, indent=2)
        archive_meta = {
            "strategy_key": strategy_key,
            "archive_dir": str(archive_dir),
            "diff_path": str(diff_file) if diff_file.exists() else None,
            "apply_reason": legacy_reason,
            "diff_status": decision_status,
            "diff_reason": decision_reasons,
        }

    result = metrics.as_dict()
    result.update({
        "bars_processed": total_processed,
        "state_out": str(state_out_path),
        "simulate_live": bool(args.simulate_live),
        "dry_run": bool(args.dry_run),
        "override": override_status,
        "risk": risk_summary,
        "anomalies": anomalies,
        "diff": {
            "updated": state_diff["updated"][:20],
            "added": state_diff["added"][:20],
            "removed": state_diff["removed"][:20],
        },
    })
    result["decision"] = {
        "status": decision_status,
        "reasons": decision_reasons,
    }
    if args.simulate_live:
        result["paper_validation"] = _build_paper_validation_summary(
            decision_status=decision_status,
            anomalies=anomalies,
            dry_run=bool(args.dry_run),
            total_processed=total_processed,
            risk_summary=risk_summary,
        )
    if archive_meta:
        result.update(archive_meta)

    rollback_triggered = args.simulate_live and bool(anomalies) and override_status["enabled"]
    if rollback_triggered:
        alert_record = _send_alert(args, True, args.dry_run, anomalies)
        result["rollback_triggered"] = True
        result["alert"] = alert_record
    else:
        result["rollback_triggered"] = False
        if args.alert_mode == "force":
            alert_record = _send_alert(args, args.simulate_live, args.dry_run, anomalies)
            result["alert"] = alert_record

    print(json.dumps(result, ensure_ascii=False))

    if args.json_out:
        with Path(args.json_out).open("w") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
