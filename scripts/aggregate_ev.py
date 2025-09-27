#!/usr/bin/env python3
"""Aggregate EV statistics from state archives to build hybrid profiles."""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

try:
    import yaml
except ImportError as exc:  # pragma: no cover - yaml is part of project deps
    raise SystemExit("PyYAML is required: pip install pyyaml") from exc


@dataclass
class BucketKey:
    session: str
    spread_band: str
    rv_band: str

    @classmethod
    def from_string(cls, key: str) -> "BucketKey":
        parts = key.split(":", 2)
        if len(parts) != 3:
            raise ValueError(f"invalid bucket key: {key}")
        return cls(parts[0], parts[1], parts[2])

    def as_dict(self) -> Dict[str, str]:
        return {
            "session": self.session,
            "spread_band": self.spread_band,
            "rv_band": self.rv_band,
        }

    def as_string(self) -> str:
        return f"{self.session}:{self.spread_band}:{self.rv_band}"


def parse_timestamp(name: str) -> Optional[datetime]:
    parts = name.split("_")
    for i in range(len(parts) - 1):
        date_part, time_part = parts[i], parts[i + 1]
        if len(date_part) == 8 and len(time_part) == 6 and date_part.isdigit() and time_part.isdigit():
            try:
                return datetime.strptime(f"{date_part}_{time_part}", "%Y%m%d_%H%M%S")
            except ValueError:
                continue
    return None


def load_state(path: Path) -> Dict:
    with path.open() as f:
        return json.load(f)


def aggregate_states(paths: Iterable[Path]) -> Dict[str, Dict[str, float]]:
    stats: Dict[str, Dict[str, float]] = defaultdict(lambda: {"alpha_sum": 0.0, "beta_sum": 0.0, "count": 0.0})
    global_stats = {"alpha_sum": 0.0, "beta_sum": 0.0, "count": 0.0}

    for path in paths:
        data = load_state(path)
        buckets = data.get("ev_buckets", {})
        for key, vals in buckets.items():
            alpha = float(vals.get("alpha", 0.0))
            beta = float(vals.get("beta", 0.0))
            agg = stats[key]
            agg["alpha_sum"] += alpha
            agg["beta_sum"] += beta
            agg["count"] += 1

        evg = data.get("ev_global", {})
        if evg:
            global_stats["alpha_sum"] += float(evg.get("alpha", 0.0))
            global_stats["beta_sum"] += float(evg.get("beta", 0.0))
            global_stats["count"] += 1

    return {"buckets": stats, "global": global_stats}


def summarise(agg: Dict[str, Dict[str, float]]) -> Dict[str, Dict]:
    bucket_summary: Dict[str, Dict] = {}
    for key, vals in agg["buckets"].items():
        count = vals["count"]
        if count <= 0:
            continue
        alpha_avg = vals["alpha_sum"] / count
        beta_avg = vals["beta_sum"] / count
        total = alpha_avg + beta_avg
        p_mean = alpha_avg / total if total > 0 else 0.0
        bucket_summary[key] = {
            "alpha_avg": alpha_avg,
            "beta_avg": beta_avg,
            "p_mean": p_mean,
            "observations": int(count),
        }

    global_summary = {}
    g_count = agg["global"]["count"]
    if g_count > 0:
        g_alpha = agg["global"]["alpha_sum"] / g_count
        g_beta = agg["global"]["beta_sum"] / g_count
        g_total = g_alpha + g_beta
        global_summary = {
            "alpha_avg": g_alpha,
            "beta_avg": g_beta,
            "p_mean": g_alpha / g_total if g_total > 0 else 0.0,
            "observations": int(g_count),
        }

    return {"buckets": bucket_summary, "global": global_summary}


def build_profile(all_summary: Dict[str, Dict], recent_summary: Dict[str, Dict], *,
                  strategy_key: str, symbol: str, mode: str,
                  files: List[Tuple[Path, Optional[datetime]]],
                  recent_count: int,
                  alpha_prior: float, beta_prior: float) -> Dict:
    buckets = []
    for key in sorted(all_summary["buckets"].keys()):
        bucket_key = BucketKey.from_string(key)
        long_term = all_summary["buckets"].get(key)
        recent = recent_summary["buckets"].get(key)
        entry = {
            "bucket": bucket_key.as_dict(),
            "long_term": long_term,
        }
        if recent:
            entry["recent"] = recent
        buckets.append(entry)

    global_section = {"long_term": all_summary["global"]}
    if recent_summary["global"]:
        global_section["recent"] = recent_summary["global"]

    latest_ts = max((ts for _, ts in files if ts), default=None)

    return {
        "meta": {
            "strategy_key": strategy_key,
            "symbol": symbol,
            "mode": mode,
            "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "files_total": len(files),
            "recent_count": min(recent_count, len(files)),
            "latest_state_ts": latest_ts.strftime("%Y-%m-%dT%H:%M:%SZ") if latest_ts else None,
            "alpha_prior": alpha_prior,
            "beta_prior": beta_prior,
        },
        "global": global_section,
        "buckets": buckets,
    }


def write_csv(path: Path, summary: Dict[str, Dict]) -> None:
    fieldnames = ["bucket", "window", "alpha_avg", "beta_avg", "p_mean", "observations"]
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for key, stats in summary["all"].items():
            writer.writerow({
                "bucket": key,
                "window": "long_term",
                **stats,
            })
        for key, stats in summary["recent"].items():
            writer.writerow({
                "bucket": key,
                "window": "recent",
                **stats,
            })


def main() -> int:
    parser = argparse.ArgumentParser(description="Aggregate EV state archives into hybrid profiles")
    parser.add_argument("--archive", default="ops/state_archive", help="Base directory of state archives")
    parser.add_argument("--strategy", required=True, help="Strategy class (module.Class) e.g. day_orb_5m.DayORB5m")
    parser.add_argument("--symbol", required=True, help="Symbol code, e.g. USDJPY")
    parser.add_argument("--mode", default="conservative", help="Mode key (conservative/bridge/...)")
    parser.add_argument("--recent", type=int, default=5, help="Number of most recent states to treat as recent window")
    parser.add_argument("--alpha-prior", type=float, default=1.0)
    parser.add_argument("--beta-prior", type=float, default=1.0)
    parser.add_argument("--out-yaml", default=None, help="Path to write YAML profile (default: configs/ev_profiles/<strategy_module>.yaml)")
    parser.add_argument("--out-csv", default=None, help="Optional path to write CSV summary")
    args = parser.parse_args()

    strategy_module, _, strategy_class = args.strategy.rpartition(".")
    if not strategy_module:
        strategy_module = args.strategy.lower()
    strategy_key = f"{strategy_module}.{strategy_class}" if strategy_class else strategy_module

    archive_dir = Path(args.archive) / strategy_key / args.symbol / args.mode
    if not archive_dir.exists() or not archive_dir.is_dir():
        raise SystemExit(f"archive directory not found: {archive_dir}")

    files: List[Tuple[Path, Optional[datetime]]] = []
    for path in sorted(archive_dir.glob("*.json")):
        files.append((path, parse_timestamp(path.name)))

    if not files:
        raise SystemExit(f"no state files found in {archive_dir}")

    files.sort(key=lambda item: item[1] or datetime.min)
    all_paths = [p for p, _ in files]
    recent_count = min(max(args.recent, 1), len(all_paths))
    recent_paths = all_paths[-recent_count:]

    all_agg = summarise(aggregate_states(all_paths))
    recent_agg = summarise(aggregate_states(recent_paths))

    profile = build_profile(
        all_agg,
        recent_agg,
        strategy_key=strategy_key,
        symbol=args.symbol,
        mode=args.mode,
        files=files,
        recent_count=recent_count,
        alpha_prior=args.alpha_prior,
        beta_prior=args.beta_prior,
    )

    out_yaml = Path(args.out_yaml) if args.out_yaml else Path("configs/ev_profiles") / f"{strategy_module}.yaml"
    out_yaml.parent.mkdir(parents=True, exist_ok=True)
    with out_yaml.open("w") as f:
        yaml.safe_dump(profile, f, sort_keys=False)
    print(f"Wrote YAML profile -> {out_yaml}")

    if args.out_csv:
        summary = {
            "all": {k: v for k, v in ((bk, data) for bk, data in all_agg["buckets"].items())},
            "recent": {k: v for k, v in ((bk, data) for bk, data in recent_agg["buckets"].items())},
        }
        write_csv(Path(args.out_csv), summary)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
