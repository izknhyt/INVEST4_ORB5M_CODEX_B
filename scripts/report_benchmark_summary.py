#!/usr/bin/env python3
"""Summarize baseline & rolling benchmark results."""
from __future__ import annotations

import argparse
import json
import logging
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple


LOGGER = logging.getLogger(__name__)


def load_json(path: Path) -> Dict:
    with path.open() as f:
        return json.load(f)


def _as_float(value: object) -> Optional[float]:
    try:
        if value is None:
            raise TypeError
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_webhook_urls(value: Optional[str]) -> List[str]:
    if not value:
        return []
    urls: List[str] = []
    for part in value.split(","):
        part = part.strip()
        if part:
            urls.append(part)
    return urls


def _normalize_drawdown_threshold(raw: Optional[float]) -> Optional[float]:
    if raw is None:
        return None
    if raw < 0:
        normalized = abs(raw)
        LOGGER.warning(
            "Received negative --max-drawdown value %s; using absolute value %s",
            raw,
            normalized,
        )
        return normalized
    return raw


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


def compute_summary(metrics: Dict) -> Dict[str, Optional[float]]:
    trades = metrics.get("trades", 0)
    wins = metrics.get("wins", 0)
    total_pips = metrics.get("total_pips", 0.0)
    sharpe = _as_float(metrics.get("sharpe"))
    max_drawdown = _as_float(metrics.get("max_drawdown"))
    win_rate = (wins / trades) if trades else 0.0
    return {
        "trades": trades,
        "wins": wins,
        "win_rate": win_rate,
        "total_pips": total_pips,
        "sharpe": sharpe,
        "max_drawdown": max_drawdown,
    }


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Summarize benchmark metrics")
    parser.add_argument("--symbol", default="USDJPY")
    parser.add_argument("--mode", default="conservative")
    parser.add_argument("--reports-dir", default="reports")
    parser.add_argument("--windows", default="365,180,90", help="Comma separated rolling windows")
    parser.add_argument("--json-out", default="reports/benchmark_summary.json")
    parser.add_argument("--plot-out", default=None, help="Optional path to save summary plot (PNG)")
    parser.add_argument("--min-sharpe", type=float, default=None, help="Optional threshold (not computed; reserved)")
    parser.add_argument("--max-drawdown", type=float, default=None, help="Optional threshold (not computed; reserved)")
    parser.add_argument("--webhook", default=None, help="Optional webhook URL(s); not used in this CLI")
    parser.add_argument("--min-sharpe", type=float, default=None, help="Warn when Sharpe ratio falls below this value")
    parser.add_argument("--max-drawdown", type=float, default=None, help="Warn when |max_drawdown| exceeds this value (pips)")
    parser.add_argument("--webhook", default=None, help="Webhook URL(s) for summary warnings (comma separated)")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    reports_dir = Path(args.reports_dir)
    baseline_path = reports_dir / "baseline" / f"{args.symbol}_{args.mode}.json"
    if not baseline_path.exists():
        print(json.dumps({"error": "baseline_not_found", "path": str(baseline_path)}))
        return 1

    baseline_metrics = load_json(baseline_path)
    baseline_summary = compute_summary(baseline_metrics)

    windows = [w.strip() for w in args.windows.split(',') if w.strip()]
    rolling_results: List[Dict] = []
    warnings: List[str] = []

    max_drawdown_threshold = _normalize_drawdown_threshold(args.max_drawdown)

    def _apply_threshold_checks(label: str, summary: Dict[str, Optional[float]]) -> None:
        sharpe_val = summary.get("sharpe")
        if args.min_sharpe is not None and sharpe_val is not None and sharpe_val < args.min_sharpe:
            warnings.append(
                f"{label} sharpe {sharpe_val:.2f} below min_sharpe {args.min_sharpe:.2f}"
            )
        drawdown_val = summary.get("max_drawdown")
        if max_drawdown_threshold is not None and drawdown_val is not None:
            magnitude = abs(drawdown_val)
            if magnitude > max_drawdown_threshold:
                warnings.append(
                    f"{label} max_drawdown {drawdown_val:.2f} exceeds threshold {max_drawdown_threshold:.2f}"
                )

    for w in windows:
        path = reports_dir / "rolling" / w / f"{args.symbol}_{args.mode}.json"
        if not path.exists():
            warnings.append(f"rolling window {w} missing")
            continue
        metrics = load_json(path)
        summary = compute_summary(metrics)
        summary["window"] = int(w)
        rolling_results.append(summary)
        if summary["total_pips"] < 0:
            warnings.append(f"rolling window {w} total_pips negative: {summary['total_pips']:.2f}")
        _apply_threshold_checks(f"rolling window {w}", summary)

    if baseline_summary["total_pips"] < 0:
        warnings.append(f"baseline total_pips negative: {baseline_summary['total_pips']:.2f}")
    _apply_threshold_checks("baseline", baseline_summary)

    payload: Dict[str, object] = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "symbol": args.symbol,
        "mode": args.mode,
        "baseline": baseline_summary,
        "rolling": sorted(rolling_results, key=lambda x: x["window"]),
        "warnings": warnings,
    }

    webhook_urls = _parse_webhook_urls(args.webhook)
    deliveries: List[Dict[str, object]] = []
    if webhook_urls and warnings:
        webhook_payload = {
            "event": "benchmark_summary_warnings",
            "symbol": args.symbol,
            "mode": args.mode,
            "warnings": warnings,
            "generated_at": payload["generated_at"],
        }
        for url in webhook_urls:
            ok, detail = _post_webhook(url, webhook_payload)
            deliveries.append({"url": url, "ok": ok, "detail": detail})
        payload["webhook"] = {"targets": webhook_urls, "deliveries": deliveries}

    json_out = Path(args.json_out)
    json_out.parent.mkdir(parents=True, exist_ok=True)
    with json_out.open("w") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    if args.plot_out:
        # Lazy import to avoid matplotlib requirement unless必要
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import pandas as pd

        rolling_df = pd.DataFrame(payload["rolling"])
        fig, axes = plt.subplots(1, 2, figsize=(10, 4))

        if not rolling_df.empty:
            axes[0].plot(rolling_df["window"], rolling_df["win_rate"] * 100, marker='o', label='rolling')
            axes[1].plot(rolling_df["window"], rolling_df["total_pips"], marker='o', label='rolling')

        baseline_wr = payload["baseline"]["win_rate"] * 100
        axes[0].axhline(baseline_wr, color='gray', linestyle='--', label='baseline')
        axes[0].set_title('Win Rate (%)')
        axes[0].set_xlabel('Window (days)')
        axes[0].set_ylabel('%')
        axes[0].legend()

        baseline_pips = payload["baseline"]["total_pips"]
        axes[1].axhline(baseline_pips, color='gray', linestyle='--', label='baseline')
        axes[1].set_title('Total Pips')
        axes[1].set_xlabel('Window (days)')
        axes[1].set_ylabel('pips')
        axes[1].legend()

        plt.tight_layout()
        plot_path = Path(args.plot_out)
        plot_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(plot_path)
        plt.close(fig)

    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
