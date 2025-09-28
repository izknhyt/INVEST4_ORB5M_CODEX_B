#!/usr/bin/env python3
"""Execute baseline and rolling benchmark simulations on demand."""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


SNAPSHOT_PATH = Path("ops/runtime_snapshot.json")
ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts._ts_utils import parse_naive_utc_timestamp


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


def _set_snapshot(snapshot: dict, key: str, ts: datetime) -> dict:
    section = snapshot.setdefault("benchmarks", {})
    section[key] = ts.isoformat()
    return snapshot


def _load_json_file(path: Path) -> Optional[Dict[str, object]]:
    if not path.exists():
        return None
    try:
        with path.open() as f:
            return json.load(f)
    except Exception:
        return None


def _extract_metrics(summary: Dict[str, object]) -> Dict[str, Optional[float]]:
    trades_val = summary.get("trades")
    wins_val = summary.get("wins")
    total_pips_val = summary.get("total_pips")
    sharpe_val = summary.get("sharpe")
    max_dd_val = summary.get("max_drawdown")

    trades = float(trades_val) if isinstance(trades_val, (int, float)) else None
    wins = float(wins_val) if isinstance(wins_val, (int, float)) else None
    total_pips = float(total_pips_val) if isinstance(total_pips_val, (int, float)) else None
    sharpe = float(sharpe_val) if isinstance(sharpe_val, (int, float)) else None
    max_drawdown = float(max_dd_val) if isinstance(max_dd_val, (int, float)) else None

    win_rate: Optional[float] = None
    if trades and wins is not None:
        try:
            win_rate = wins / trades if trades else None
        except ZeroDivisionError:
            win_rate = None

    return {
        "trades": trades,
        "wins": wins,
        "win_rate": win_rate,
        "total_pips": total_pips,
        "sharpe": sharpe,
        "max_drawdown": max_drawdown,
    }


def _diff_metrics(
    prev: Dict[str, Optional[float]],
    new: Dict[str, Optional[float]],
    *,
    pips_threshold: float,
    winrate_threshold: float,
    sharpe_threshold: float,
    max_drawdown_threshold: float,
) -> Tuple[bool, Dict[str, float]]:
    triggered = False
    details: Dict[str, float] = {}

    def _check_threshold(
        prev_value: Optional[float],
        new_value: Optional[float],
        threshold: Optional[float],
        key: str,
    ) -> None:
        nonlocal triggered
        if prev_value is None or new_value is None or threshold is None:
            return
        delta = new_value - prev_value
        if abs(delta) >= threshold:
            triggered = True
            details[key] = delta

    _check_threshold(prev.get("total_pips"), new.get("total_pips"), pips_threshold, "delta_total_pips")
    _check_threshold(prev.get("win_rate"), new.get("win_rate"), winrate_threshold, "delta_win_rate")
    _check_threshold(prev.get("sharpe"), new.get("sharpe"), sharpe_threshold, "delta_sharpe")
    _check_threshold(
        prev.get("max_drawdown"),
        new.get("max_drawdown"),
        max_drawdown_threshold,
        "delta_max_drawdown",
    )

    return triggered, details


def _parse_webhook_urls(value: Optional[str]) -> List[str]:
    if not value:
        return []
    urls: List[str] = []
    for part in value.split(","):
        part = part.strip()
        if part:
            urls.append(part)
    return urls


def _post_webhook(url: str, payload: Dict[str, object], timeout: float = 5.0) -> Tuple[bool, str]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return True, f"status={resp.status}"
    except urllib.error.HTTPError as exc:
        return False, f"http_error={exc.code}"
    except urllib.error.URLError as exc:
        return False, f"url_error={exc.reason}"
    except Exception as exc:  # pragma: no cover
        return False, f"unexpected_error={type(exc).__name__}:{exc}"


def _parse_ts(value: str) -> datetime:
    return parse_naive_utc_timestamp(
        value,
        fallback_formats=("%Y-%m-%d %H:%M:%S",),
    )


def _filter_window(rows: List[dict], days: int) -> List[dict]:
    if not rows:
        return []
    latest_ts = _parse_ts(rows[-1]["timestamp"])
    cutoff = latest_ts - timedelta(days=days)
    return [row for row in rows if _parse_ts(row["timestamp"]) >= cutoff]


def _read_rows(path: Path) -> List[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [row for row in reader]


def _write_temp(rows: Iterable[dict]) -> Path:
    tmp = tempfile.NamedTemporaryFile(prefix="benchmark_", suffix=".csv", delete=False, mode="w", newline="", encoding="utf-8")
    fieldnames = ["timestamp", "symbol", "tf", "o", "h", "l", "c", "v", "spread"]
    with tmp:
        writer = csv.DictWriter(tmp, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})
    return Path(tmp.name)


def _run_sim(csv_path: Path, args: argparse.Namespace, json_out: Path,
             dump_daily: Path | None = None, out_dir: Optional[Path] = None) -> int:
    cmd = [
        sys.executable,
        str(ROOT / "scripts/run_sim.py"),
        "--csv", str(csv_path),
        "--symbol", args.symbol,
        "--mode", args.mode,
        "--equity", str(args.equity),
        "--json-out", str(json_out),
        "--dump-max", "0",
    ]
    if dump_daily is not None:
        dump_daily.parent.mkdir(parents=True, exist_ok=True)
        cmd += ["--dump-daily", str(dump_daily)]
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        cmd += ["--out-dir", str(out_dir)]
    if args.threshold_lcb is not None:
        cmd += ["--threshold-lcb", str(args.threshold_lcb)]
    if args.min_or_atr is not None:
        cmd += ["--min-or-atr", str(args.min_or_atr)]
    if args.rv_cuts:
        cmd += ["--rv-cuts", args.rv_cuts]
    if args.allow_low_rv:
        cmd.append("--allow-low-rv")
    if args.allowed_sessions:
        cmd += ["--allowed-sessions", args.allowed_sessions]
    if args.or_n is not None:
        cmd += ["--or-n", str(args.or_n)]
    if args.k_tp is not None:
        cmd += ["--k-tp", str(args.k_tp)]
    if args.k_sl is not None:
        cmd += ["--k-sl", str(args.k_sl)]
    if args.k_tr is not None:
        cmd += ["--k-tr", str(args.k_tr)]
    if args.warmup is not None:
        cmd += ["--warmup", str(args.warmup)]
    if args.prior_alpha is not None:
        cmd += ["--prior-alpha", str(args.prior_alpha)]
    if args.prior_beta is not None:
        cmd += ["--prior-beta", str(args.prior_beta)]
    if args.include_expected_slip:
        cmd.append("--include-expected-slip")
    if args.ev_mode:
        cmd += ["--ev-mode", args.ev_mode]
    if args.size_floor is not None:
        cmd += ["--size-floor", str(args.size_floor)]
    result = subprocess.run(cmd, check=False)
    return result.returncode


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Run baseline + rolling benchmarks")
    parser.add_argument("--bars", default=None, help="CSV path (default: validated/<symbol>/5m.csv)")
    parser.add_argument("--symbol", default="USDJPY")
    parser.add_argument("--mode", default="conservative", choices=["conservative", "bridge"])
    parser.add_argument("--equity", type=float, default=100_000.0)
    parser.add_argument("--windows", default="365,180,90", help="Rolling windows in days (comma separated)")
    parser.add_argument("--snapshot", default=str(SNAPSHOT_PATH))
    parser.add_argument("--reports-dir", default="reports", help="Where to store metrics JSON")
    parser.add_argument("--runs-dir", default="runs", help="Directory to store run outputs when capturing baseline")
    parser.add_argument("--webhook", default=None, help="Webhook URL(s) for alert (comma separated)")
    parser.add_argument("--alert-pips", type=float, default=50.0, help="Abs diff in total_pips to trigger alert")
    parser.add_argument("--alert-winrate", type=float, default=0.05, help="Abs diff in win_rate to trigger alert")
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

    rows = _read_rows(bars_path)
    if not rows:
        print(json.dumps({"message": "no_rows", "path": str(bars_path)}))
        return 0

    reports_dir = Path(args.reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)

    baseline_out = reports_dir / "baseline" / f"{args.symbol}_{args.mode}.json"
    baseline_out.parent.mkdir(parents=True, exist_ok=True)
    prev_baseline_summary = _load_json_file(baseline_out)
    prev_metrics = _extract_metrics(prev_baseline_summary) if prev_baseline_summary else None

    runs_dir_path = Path(args.runs_dir) if args.runs_dir else None
    webhook_urls = _parse_webhook_urls(args.webhook)

    rc = 0
    if not args.dry_run:
        rc = _run_sim(bars_path, args, baseline_out, out_dir=runs_dir_path)
        if rc != 0:
            return rc

    baseline_summary = _load_json_file(baseline_out) if not args.dry_run else prev_baseline_summary
    if baseline_summary is None:
        baseline_summary = {}
    baseline_metrics = _extract_metrics(baseline_summary)

    alert_info: Dict[str, object] = {"triggered": False}
    if not args.dry_run and prev_metrics:
        triggered, deltas = _diff_metrics(
            prev_metrics,
            baseline_metrics,
            pips_threshold=args.alert_pips,
            winrate_threshold=args.alert_winrate,
            sharpe_threshold=args.alert_sharpe,
            max_drawdown_threshold=args.alert_max_drawdown,
        )
        if triggered:
            payload = {
                "event": "benchmark_shift",
                "symbol": args.symbol,
                "mode": args.mode,
                "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "thresholds": {
                    "total_pips": args.alert_pips,
                    "win_rate": args.alert_winrate,
                    "sharpe": args.alert_sharpe,
                    "max_drawdown": args.alert_max_drawdown,
                },
                "metrics_prev": prev_metrics,
                "metrics_new": baseline_metrics,
                "deltas": deltas,
                "report_path": str(baseline_out),
            }
            deliveries = []
            for url in webhook_urls:
                ok, detail = _post_webhook(url, payload)
                deliveries.append({"url": url, "ok": ok, "detail": detail})
            alert_info = {
                "triggered": True,
                "payload": payload,
                "deliveries": deliveries,
            }
        else:
            alert_info = {"triggered": False, "reason": "below_threshold"}
    elif not args.dry_run:
        alert_info = {"triggered": False, "reason": "no_previous_baseline"}

    windows = [int(x.strip()) for x in args.windows.split(',') if x.strip()]
    tmp_files: List[Path] = []
    rolling_outputs: List[Dict[str, object]] = []
    try:
        for window in windows:
            subset = _filter_window(rows, window)
            if not subset:
                continue
            tmp_csv = _write_temp(subset)
            tmp_files.append(tmp_csv)
            out_dir = reports_dir / "rolling" / str(window)
            out_dir.mkdir(parents=True, exist_ok=True)
            json_out = out_dir / f"{args.symbol}_{args.mode}.json"
            if args.dry_run:
                rolling_outputs.append({"window": window, "path": str(json_out), "skipped": True})
                continue
            rc = _run_sim(tmp_csv, args, json_out)
            if rc != 0:
                return rc
            rolling_outputs.append({"window": window, "path": str(json_out)})
    finally:
        for tmp in tmp_files:
            try:
                tmp.unlink()
            except OSError:
                pass

    if args.dry_run:
        result = {
            "baseline": str(baseline_out),
            "baseline_metrics": baseline_metrics,
            "rolling": rolling_outputs,
            "alert": alert_info,
        }
        print(json.dumps(result, ensure_ascii=False))
        return 0

    latest_ts = _parse_ts(rows[-1]["timestamp"])
    base_result: Dict[str, object] = {
        "baseline": str(baseline_out),
        "baseline_metrics": baseline_metrics,
        "rolling": rolling_outputs,
        "windows": windows,
        "latest_ts": latest_ts.isoformat(),
        "alert": alert_info,
    }

    index_rc = None
    if runs_dir_path:
        rebuild_cmd = [
            sys.executable,
            str(ROOT / "scripts/rebuild_runs_index.py"),
            "--runs-dir", str(runs_dir_path),
            "--out", str(runs_dir_path / "index.csv"),
        ]
        rebuild_proc = subprocess.run(
            rebuild_cmd,
            check=False,
            capture_output=True,
            text=True,
        )
        index_rc = rebuild_proc.returncode
        if index_rc != 0:
            error_payload: Dict[str, object] = {
                "message": "rebuild_runs_index_failed",
                "returncode": index_rc,
            }
            if rebuild_proc.stdout:
                stdout_text = rebuild_proc.stdout.rstrip()
                if stdout_text:
                    error_payload["stdout"] = stdout_text
                    print(
                        "[rebuild_runs_index.py stdout]\n" + rebuild_proc.stdout,
                        file=sys.stderr,
                        end="",
                    )
            if rebuild_proc.stderr:
                stderr_text = rebuild_proc.stderr.rstrip()
                if stderr_text:
                    error_payload["stderr"] = stderr_text
                    print(
                        "[rebuild_runs_index.py stderr]\n" + rebuild_proc.stderr,
                        file=sys.stderr,
                        end="",
                    )
            failure_result = {**base_result, "runs_index_rc": index_rc, "error": error_payload}
            print(json.dumps(failure_result, ensure_ascii=False))
            return index_rc

    snapshot_path = Path(args.snapshot)
    snapshot = _load_snapshot(snapshot_path)
    key = f"{args.symbol}_{args.mode}"
    snapshot = _set_snapshot(snapshot, key, latest_ts)
    _save_snapshot(snapshot_path, snapshot)
    result = {**base_result, "runs_index_rc": index_rc}
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
