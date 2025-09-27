#!/usr/bin/env python3
"""Summarize baseline & rolling benchmark results."""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List


def load_json(path: Path) -> Dict:
    with path.open() as f:
        return json.load(f)


def compute_summary(metrics: Dict) -> Dict[str, float]:
    trades = metrics.get("trades", 0)
    wins = metrics.get("wins", 0)
    total_pips = metrics.get("total_pips", 0.0)
    win_rate = (wins / trades) if trades else 0.0
    return {
        "trades": trades,
        "wins": wins,
        "win_rate": win_rate,
        "total_pips": total_pips,
    }


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Summarize benchmark metrics")
    parser.add_argument("--symbol", default="USDJPY")
    parser.add_argument("--mode", default="conservative")
    parser.add_argument("--reports-dir", default="reports")
    parser.add_argument("--windows", default="365,180,90", help="Comma separated rolling windows")
    parser.add_argument("--json-out", default="reports/benchmark_summary.json")
    parser.add_argument("--plot-out", default=None, help="Optional path to save summary plot (PNG)")
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

    if baseline_summary["total_pips"] < 0:
        warnings.append(f"baseline total_pips negative: {baseline_summary['total_pips']:.2f}")

    payload = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "symbol": args.symbol,
        "mode": args.mode,
        "baseline": baseline_summary,
        "rolling": sorted(rolling_results, key=lambda x: x["window"]),
        "warnings": warnings,
    }

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
