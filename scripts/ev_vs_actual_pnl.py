#!/usr/bin/env python3
"""CLI utility to inspect EV vs realized PnL gaps from run artifacts.

Features:
- Select a specific run (defaults to the latest) and produce daily summaries.
- Combine multiple runs to compute aggregate statistics.
- Emit structured JSON (optionally) so the output can be piped into other tools.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, asdict
from datetime import datetime
import math
from os import PathLike
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Union

import pandas as pd


NUMERIC_COLUMNS = [
    "ev_lcb",
    "pnl_pips",
    "cost_pips",
    "slip_est",
    "slip_real",
    "tp_pips",
    "sl_pips",
    "or_atr_ratio",
    "min_or_atr_ratio",
]


def _normalize_path(value: Optional[Union[str, PathLike[str], Path]]) -> Optional[Path]:
    if value is None:
        return None
    return Path(value).expanduser().resolve()


@dataclass
class DailySummary:
    run_id: str
    days_with_records: int
    realized_total: float
    ev_total: float
    gap_total: float
    mean_daily_gap: float
    max_positive_gap: float
    max_negative_gap: float
    sharpe: Optional[float] = None
    max_drawdown: Optional[float] = None

    def to_dict(self) -> Dict[str, float]:
        return asdict(self)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarise EV vs realized PnL gaps from run artifacts")
    parser.add_argument("--runs-dir", default="runs", help="Directory containing run subfolders")
    parser.add_argument("--run-id", default=None, help="Specific run ID to inspect (defaults to latest)")
    parser.add_argument("--list-runs", action="store_true", help="List available run IDs and exit")
    parser.add_argument("--all-runs", action="store_true", help="Aggregate across all runs instead of a single run")
    parser.add_argument("--top-n", type=int, default=5, help="Number of top positive/negative gap days to display")
    parser.add_argument("--output-json", default=None, help="Write summary information to JSON file")
    parser.add_argument("--show-daily", action="store_true", help="Print merged daily table for the selected run")
    parser.add_argument("--store-dir", default=None, help="Persist summaries under this directory (e.g., analysis/ev_pipeline)")
    parser.add_argument("--store-daily", action="store_true", help="When storing, also persist merged daily CSV")
    parser.add_argument("--quiet", action="store_true", help="Suppress stdout JSON output (useful when storing only)")
    return parser.parse_args()


def _load_records(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"records.csv not found at {path}")
    df = pd.read_csv(path)
    if "ts" in df.columns:
        df["ts"] = pd.to_datetime(df["ts"], errors="coerce")
    for col in NUMERIC_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _load_daily(path: Optional[Path]) -> Optional[pd.DataFrame]:
    if path is None or not path.exists():
        return None
    df = pd.read_csv(path)
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df


def _collect_record_paths(runs_dir: Path) -> List[Path]:
    if not runs_dir.exists():
        return []
    return sorted(runs_dir.glob("*/records.csv"))


def _select_run(record_paths: List[Path], run_id: Optional[str]) -> Path:
    if not record_paths:
        raise SystemExit("No runs with records.csv were found.")
    if run_id is None:
        return record_paths[-1]
    for path in record_paths:
        if path.parent.name == run_id:
            return path
    raise SystemExit(f"run_id '{run_id}' not found. Available: {[p.parent.name for p in record_paths]}")


def _summarise_trade_records(records_df: pd.DataFrame) -> pd.DataFrame:
    if "pnl_pips" not in records_df.columns:
        return pd.DataFrame()
    trade_records = records_df.loc[records_df["pnl_pips"].notna()].copy()
    if trade_records.empty:
        return pd.DataFrame()
    if "ts" in trade_records.columns:
        trade_records["date"] = trade_records["ts"].dt.floor("D")
    else:
        raise ValueError("records.csv is missing 'ts' column required for daily aggregation")
    grouped = (
        trade_records.groupby("date")[["pnl_pips", "ev_lcb"]]
        .sum()
        .rename(columns={"pnl_pips": "realized_pnl_pips", "ev_lcb": "ev_lcb_sum"})
        .reset_index()
    )
    grouped["ev_gap"] = grouped["realized_pnl_pips"] - grouped["ev_lcb_sum"]
    return grouped


def _merge_with_daily(daily_df: Optional[pd.DataFrame], trade_daily: pd.DataFrame) -> pd.DataFrame:
    if daily_df is None or daily_df.empty:
        # If run-specific daily does not exist, fall back to trade_daily only.
        return trade_daily
    daily = daily_df.copy()
    if daily["date"].dtype != "datetime64[ns]":
        daily["date"] = pd.to_datetime(daily["date"], errors="coerce")
    merged = daily.merge(trade_daily, how="left", on="date")
    return merged


def _extract_metric(metrics: Optional[Dict[str, Any]], key: str) -> Optional[float]:
    if not metrics:
        return None
    value = metrics.get(key)
    try:
        if value is None:
            raise TypeError
        return float(value)
    except (TypeError, ValueError):
        return None


def _build_summary(
    run_id: str,
    merged: pd.DataFrame,
    metrics: Optional[Dict[str, Any]],
) -> DailySummary:
    sharpe = _extract_metric(metrics, "sharpe")
    max_drawdown = _extract_metric(metrics, "max_drawdown")
    filled = merged.dropna(subset=["realized_pnl_pips", "ev_lcb_sum"], how="any").copy()
    if filled.empty:
        return DailySummary(
            run_id=run_id,
            days_with_records=0,
            realized_total=0.0,
            ev_total=0.0,
            gap_total=0.0,
            mean_daily_gap=0.0,
            max_positive_gap=0.0,
            max_negative_gap=0.0,
            sharpe=sharpe,
            max_drawdown=max_drawdown,
        )
    filled["ev_gap"] = filled["realized_pnl_pips"] - filled["ev_lcb_sum"]
    return DailySummary(
        run_id=run_id,
        days_with_records=int(len(filled)),
        realized_total=float(filled["realized_pnl_pips"].sum()),
        ev_total=float(filled["ev_lcb_sum"].sum()),
        gap_total=float(filled["ev_gap"].sum()),
        mean_daily_gap=float(filled["ev_gap"].mean()),
        max_positive_gap=float(filled["ev_gap"].max()),
        max_negative_gap=float(filled["ev_gap"].min()),
        sharpe=sharpe,
        max_drawdown=max_drawdown,
    )


def _show_top_days(merged: pd.DataFrame, top_n: int) -> Dict[str, List[Dict[str, Any]]]:
    output: Dict[str, List[Dict[str, Any]]] = {}
    filled = merged.dropna(subset=["realized_pnl_pips", "ev_lcb_sum"], how="any").copy()
    if filled.empty:
        return output
    filled["ev_gap"] = filled["realized_pnl_pips"] - filled["ev_lcb_sum"]
    top_n = max(1, top_n)
    top_pos = filled.nlargest(top_n, "ev_gap")[["date", "realized_pnl_pips", "ev_lcb_sum", "ev_gap"]]
    top_neg = filled.nsmallest(top_n, "ev_gap")[["date", "realized_pnl_pips", "ev_lcb_sum", "ev_gap"]]
    output["top_positive_gap_days"] = _to_serializable_records(top_pos.to_dict(orient="records"))
    output["top_negative_gap_days"] = _to_serializable_records(top_neg.to_dict(orient="records"))
    return output


def _convert_value(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime().isoformat()
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            value = value.item()
        except Exception:
            value = str(value)
    if isinstance(value, float):
        if math.isnan(value):
            return None
        return float(value)
    if pd.isna(value):  # handles NaT/None-like
        return None
    return value


def _to_serializable_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    converted: List[Dict[str, Any]] = []
    for rec in records:
        clean = {k: _convert_value(v) for k, v in rec.items()}
        converted.append(clean)
    return converted


def process_single_run(
    record_path: Path,
    runs_dir: Path,
    top_n: int,
    include_daily: bool,
) -> Dict[str, object]:
    run_id = record_path.parent.name
    run_dir = record_path.parent
    records_df = _load_records(record_path)
    trade_daily = _summarise_trade_records(records_df)

    daily_path = run_dir / "daily.csv"
    daily_df = _load_daily(daily_path)
    merged = _merge_with_daily(daily_df, trade_daily)

    metrics_path = run_dir / "metrics.json"
    metrics = {}
    if metrics_path.exists():
        try:
            metrics = json.loads(metrics_path.read_text())
        except json.JSONDecodeError:
            metrics = {}

    summary = _build_summary(run_id, merged, metrics)
    top_days = _show_top_days(merged, top_n)

    result: Dict[str, object] = {
        "run_id": run_id,
        "summary": summary.to_dict(),
        "top_days": top_days,
    }

    if include_daily:
        result["daily"] = _to_serializable_records(merged.to_dict(orient="records"))

    return result


def process_all_runs(record_paths: Iterable[Path]) -> Dict[str, object]:
    frames: List[pd.DataFrame] = []
    for path in record_paths:
        df = _load_records(path)
        trades = df.loc[df["pnl_pips"].notna()].copy()
        if trades.empty or "ts" not in trades.columns:
            continue
        trades["date"] = trades["ts"].dt.floor("D")
        summary = (
            trades.groupby("date")[["pnl_pips", "ev_lcb"]]
            .sum()
            .rename(columns={"pnl_pips": "realized_pnl_pips", "ev_lcb": "ev_lcb_sum"})
            .reset_index()
        )
        summary["run_id"] = path.parent.name
        frames.append(summary)

    if not frames:
        return {"runs": [], "overall": {}}

    combined = pd.concat(frames, ignore_index=True)
    combined["ev_gap"] = combined["realized_pnl_pips"] - combined["ev_lcb_sum"]

    per_run = (
        combined.groupby("run_id")
        .agg(
            days_with_pnl=("date", "nunique"),
            realized_total=("realized_pnl_pips", "sum"),
            ev_total=("ev_lcb_sum", "sum"),
            gap_total=("ev_gap", "sum"),
            mean_gap=("ev_gap", "mean"),
            max_gap=("ev_gap", "max"),
            min_gap=("ev_gap", "min"),
        )
        .reset_index()
    )

    overall = {
        "runs": int(per_run["run_id"].nunique()),
        "days_with_pnl": int(combined["date"].nunique()),
        "realized_total": float(per_run["realized_total"].sum()),
        "ev_total": float(per_run["ev_total"].sum()),
        "gap_total": float(per_run["gap_total"].sum()),
    }

    runs_records = _to_serializable_records(per_run.to_dict(orient="records"))

    return {
        "runs": runs_records,
        "overall": overall,
    }


def store_run_summary(
    runs_dir: Path,
    run_id: Optional[str],
    store_dir: Path,
    store_daily: bool = False,
    top_n: int = 5,
) -> Dict[str, Any]:
    runs_dir_path = _normalize_path(runs_dir)
    store_dir_path = _normalize_path(store_dir)
    if runs_dir_path is None or store_dir_path is None:
        raise ValueError("runs_dir and store_dir must be provided")
    record_paths = _collect_record_paths(runs_dir_path)
    record_path = _select_run(record_paths, run_id)
    include_daily = bool(store_daily)
    output = process_single_run(record_path, runs_dir_path, top_n, include_daily)
    _store_single_run(store_dir_path, output, record_paths, store_daily)
    return output


def store_all_runs(runs_dir: Path, store_dir: Path) -> Dict[str, Any]:
    runs_dir_path = _normalize_path(runs_dir)
    store_dir_path = _normalize_path(store_dir)
    if runs_dir_path is None or store_dir_path is None:
        raise ValueError("runs_dir and store_dir must be provided")
    record_paths = _collect_record_paths(runs_dir_path)
    aggregated = process_all_runs(record_paths)
    _store_all_runs(store_dir_path, aggregated)
    return aggregated


def _store_single_run(
    store_dir: Path,
    output: Dict[str, Any],
    record_paths: List[Path],
    store_daily: bool,
) -> None:
    store_dir.mkdir(parents=True, exist_ok=True)
    run_id = output.get("run_id")
    if not run_id:
        raise ValueError("run_id missing from output; cannot store")

    run_store = store_dir / run_id
    run_store.mkdir(parents=True, exist_ok=True)

    summary_path = run_store / "summary.json"
    summary_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    daily_records = output.get("daily")
    if store_daily and daily_records:
        pd.DataFrame(daily_records).to_csv(run_store / "daily.csv", index=False)

    # Build aggregate listing of per-run summaries (including any previous ones)
    summary_entries: List[Dict[str, Any]] = []
    for existing_summary in store_dir.glob("*/summary.json"):
        try:
            data = json.loads(existing_summary.read_text())
        except json.JSONDecodeError:
            continue
        summary = data.get("summary")
        if summary:
            summary_entries.append(summary)
    if summary_entries:
        (store_dir / "run_summary.json").write_text(
            json.dumps(summary_entries, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        pd.DataFrame(summary_entries).to_csv(store_dir / "run_summary.csv", index=False)

    aggregated = process_all_runs(record_paths)
    (store_dir / "overall.json").write_text(
        json.dumps(aggregated, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    runs_df = pd.DataFrame(aggregated.get("runs", []))
    if not runs_df.empty:
        runs_df.to_csv(store_dir / "overall_runs.csv", index=False)


def _store_all_runs(store_dir: Path, aggregated: Dict[str, Any]) -> None:
    store_dir.mkdir(parents=True, exist_ok=True)
    (store_dir / "overall.json").write_text(
        json.dumps(aggregated, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    runs_df = pd.DataFrame(aggregated.get("runs", []))
    if not runs_df.empty:
        runs_df.to_csv(store_dir / "overall_runs.csv", index=False)


def main() -> None:
    args = parse_args()
    runs_dir = _normalize_path(args.runs_dir)
    if runs_dir is None:
        raise ValueError("runs_dir must be provided")
    record_paths = _collect_record_paths(runs_dir)

    if args.list_runs:
        if not record_paths:
            print("No runs found.")
            return
        for path in record_paths:
            print(path.parent.name)
        return

    if args.all_runs:
        output = process_all_runs(record_paths)
    else:
        record_path = _select_run(record_paths, args.run_id)
        include_daily = bool(args.show_daily or args.store_daily or args.store_dir)
        output = process_single_run(record_path, runs_dir, args.top_n, include_daily)

    store_dir = _normalize_path(args.store_dir)
    if store_dir is not None:
        if args.all_runs:
            _store_all_runs(store_dir, output)
        else:
            _store_single_run(store_dir, output, record_paths, args.store_daily)

    if not args.quiet:
        print(json.dumps(output, indent=2, ensure_ascii=False))

    out_path = _normalize_path(args.output_json)
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
