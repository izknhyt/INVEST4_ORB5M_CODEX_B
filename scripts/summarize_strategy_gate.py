#!/usr/bin/env python3
"""Summarise strategy gate debug records for Day ORB simple reboot analysis."""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

NUMERIC_FIELDS: tuple[str, ...] = (
    "or_atr_ratio",
    "min_or_atr_ratio",
    "atr_pips",
    "min_atr_pips",
    "max_atr_pips",
    "micro_trend",
    "loss_streak",
    "max_loss_streak",
    "daily_loss_pips",
    "max_daily_loss_pips",
    "daily_trade_count",
    "max_daily_trade_count",
    "signals_today",
    "max_signals_per_day",
    "cooldown_bars",
    "bars_since",
    "qty",
    "p_lcb",
    "sl_pips",
)

CATEGORICAL_FIELDS: tuple[str, ...] = (
    "rv_band",
    "spread_band",
    "allow_low_rv",
)

DISPLAY_NUMERIC_ORDER: List[str] = [
    "or_atr_ratio",
    "min_or_atr_ratio",
    "atr_pips",
    "min_atr_pips",
    "max_atr_pips",
    "micro_trend",
    "loss_streak",
    "max_loss_streak",
    "daily_loss_pips",
    "max_daily_loss_pips",
    "daily_trade_count",
    "max_daily_trade_count",
    "signals_today",
    "max_signals_per_day",
    "cooldown_bars",
    "bars_since",
    "qty",
    "p_lcb",
    "sl_pips",
]

DISPLAY_CATEGORICAL_ORDER: List[str] = [
    "rv_band",
    "spread_band",
    "allow_low_rv",
]


@dataclass
class NumericStats:
    count: int = 0
    total: float = 0.0
    minimum: Optional[float] = None
    maximum: Optional[float] = None

    def add(self, value: Optional[float]) -> None:
        if value is None:
            return
        if not math.isfinite(value):
            return
        self.count += 1
        self.total += value
        if self.minimum is None or value < self.minimum:
            self.minimum = value
        if self.maximum is None or value > self.maximum:
            self.maximum = value

    @property
    def mean(self) -> Optional[float]:
        if self.count == 0:
            return None
        return self.total / self.count


class ReasonSummary:
    def __init__(self, numeric_fields: Iterable[str], categorical_fields: Iterable[str]) -> None:
        self.count: int = 0
        self.numeric: Dict[str, NumericStats] = {
            field: NumericStats() for field in numeric_fields
        }
        self.categorical: Dict[str, Counter[str]] = {
            field: Counter() for field in categorical_fields
        }

    def update(self, row: Dict[str, str]) -> None:
        self.count += 1
        for field, stats in self.numeric.items():
            stats.add(_coerce_float(row.get(field)))
        for field, counter in self.categorical.items():
            value = row.get(field)
            if value is None:
                continue
            value_str = str(value).strip()
            if not value_str:
                continue
            counter[value_str] += 1

    def to_dict(self) -> Dict[str, object]:
        numeric_payload = {
            field: {
                "count": stats.count,
                "mean": stats.mean,
                "min": stats.minimum,
                "max": stats.maximum,
            }
            for field, stats in self.numeric.items()
            if stats.count
        }
        categorical_payload = {
            field: counter.most_common()
            for field, counter in self.categorical.items()
            if counter
        }
        return {
            "count": self.count,
            "numeric": numeric_payload,
            "categorical": categorical_payload,
        }


def _coerce_float(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        value = float(value)
        return value if math.isfinite(value) else None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = float(text)
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None


def _resolve_records_path(args: argparse.Namespace) -> Path:
    if args.records:
        path = Path(args.records)
        if not path.is_absolute():
            path = Path.cwd() / path
        return path
    if args.run_dir:
        run_dir = Path(args.run_dir)
        if not run_dir.is_absolute():
            run_dir = Path.cwd() / run_dir
        return run_dir / "records.csv"
    raise SystemExit("Either --records or --run-dir must be provided")


def _load_records(path: Path, stage: str) -> Dict[str, ReasonSummary]:
    if not path.exists():
        raise SystemExit(f"records.csv not found at {path}")
    summaries: Dict[str, ReasonSummary] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if "stage" not in reader.fieldnames:
            raise SystemExit("records.csv is missing the 'stage' column")
        for row in reader:
            row_stage = (row.get("stage") or "").strip()
            reason_stage = (
                (row.get("reason_stage") or row.get("reason") or "").strip()
            )
            if stage not in {row_stage, reason_stage}:
                continue
            reason = reason_stage or row_stage or "unknown"
            summary = summaries.get(reason)
            if summary is None:
                summary = ReasonSummary(NUMERIC_FIELDS, CATEGORICAL_FIELDS)
                summaries[reason] = summary
            summary.update(row)
    return summaries


def _format_numeric(field: str, stats: NumericStats) -> str:
    mean = stats.mean
    if mean is None:
        return ""
    if stats.minimum is not None and stats.maximum is not None:
        return f"{field}: mean={mean:.3f} (min={stats.minimum:.3f}, max={stats.maximum:.3f})"
    return f"{field}: mean={mean:.3f}"


def _format_categorical(field: str, counter: Counter[str], limit: int = 3) -> str:
    if not counter:
        return ""
    parts = [f"{value}×{count}" for value, count in counter.most_common(limit)]
    return f"{field}: {', '.join(parts)}"


def _render_text_summary(summaries: Dict[str, ReasonSummary], limit: int) -> str:
    lines: List[str] = []
    for reason, summary in sorted(
        summaries.items(), key=lambda item: item[1].count, reverse=True
    )[:limit]:
        lines.append(f"Reason: {reason} (count={summary.count})")
        for field in DISPLAY_CATEGORICAL_ORDER:
            text = _format_categorical(field, summary.categorical.get(field, Counter()))
            if text:
                lines.append(f"  {text}")
        for field in DISPLAY_NUMERIC_ORDER:
            stats = summary.numeric.get(field)
            if not stats:
                continue
            text = _format_numeric(field, stats)
            if text:
                lines.append(f"  {text}")
        lines.append("")
    return "\n".join(lines).rstrip()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Summarise strategy_gate records to support Day ORB reboot tuning"
    )
    parser.add_argument("--records", help="Path to records.csv generated by run_sim")
    parser.add_argument(
        "--run-dir",
        help="Run directory containing records.csv (alternatively provide --records)",
    )
    parser.add_argument(
        "--stage",
        dest="stages",
        action="append",
        help="Record stage to summarise (repeatable; default: strategy_gate)",
    )
    parser.add_argument(
        "--limit",
        "--top",
        dest="limit",
        type=int,
        default=10,
        help="Number of reasons to display",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit summary as JSON instead of formatted text",
    )
    parser.add_argument(
        "--out-json",
        help="Write JSON summary to the given path (implies --json)",
    )
    args = parser.parse_args(argv)

    if args.out_json and not args.json:
        args.json = True

    records_path = _resolve_records_path(args)
    stages = args.stages or ["strategy_gate"]

    stage_payloads: Dict[str, Dict[str, object]] = {}
    text_sections: List[str] = []

    for stage in stages:
        summaries = _load_records(records_path, stage)
        ordered = sorted(
            summaries.items(), key=lambda item: item[1].count, reverse=True
        )
        if not ordered:
            stage_payloads[stage] = {"total_count": 0, "reasons": {}}
            if not args.json:
                text_sections.append(
                    f"No records found for stage '{stage}' in {records_path}"
                )
            continue

        stage_payloads[stage] = {
            "total_count": sum(summary.count for _, summary in ordered),
            "reasons": {
                reason: summary.to_dict()
                for reason, summary in ordered
            },
        }

        if not args.json:
            text_sections.append(f"[Stage: {stage}]")
            text_sections.append(_render_text_summary(summaries, args.limit))

    if args.json:
        multi_stage = len(stages) > 1 or args.out_json
        if not multi_stage:
            stage = stages[0]
            payload = stage_payloads.get(stage, {"total_count": 0, "reasons": {}})
            if not payload.get("total_count"):
                print(f"No records found for stage '{stage}' in {records_path}")
                return 0
            json_payload = payload["reasons"]
        else:
            json_payload = {
                "records_path": str(records_path),
                "stages": stage_payloads,
            }

        text = json.dumps(json_payload, ensure_ascii=False, indent=2)
        print(text)

        if args.out_json:
            out_path = Path(args.out_json)
            if not out_path.is_absolute():
                out_path = Path.cwd() / out_path
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(text, encoding="utf-8")
        return 0

    if not text_sections:
        print(
            f"No records found for stages {', '.join(stages)} in {records_path}"
        )
        return 0

    print("\n\n".join(section for section in text_sections if section))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
