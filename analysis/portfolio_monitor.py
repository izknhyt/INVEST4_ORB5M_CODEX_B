"""Portfolio monitoring utilities for router-driven multi-strategy runs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from configs.strategies.loader import StrategyManifest, load_manifest
from core.router_pipeline import PortfolioTelemetry, build_portfolio_state
from router.router_v1 import PortfolioState


@dataclass
class StrategySeries:
    """Container for a strategy equity curve."""

    manifest: StrategyManifest
    equity_curve: List[Tuple[datetime, str, float]]


def _parse_timestamp(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Invalid ISO timestamp: {value}") from exc


def _coerce_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Expected numeric value, received {value!r}") from exc


def _normalise_equity_curve(raw: Sequence[Any]) -> List[Tuple[datetime, str, float]]:
    """Normalise various curve formats into `(datetime, original, equity)` tuples."""

    normalised: List[Tuple[datetime, str, float]] = []
    for entry in raw:
        if isinstance(entry, Mapping):
            ts = entry.get("ts") or entry.get("timestamp") or entry.get("date")
            equity = entry.get("equity") or entry.get("value") or entry.get("equity_value")
        elif isinstance(entry, Sequence) and len(entry) >= 2:
            ts, equity = entry[0], entry[1]
        else:
            raise ValueError(f"Unsupported equity curve entry: {entry!r}")
        if ts is None:
            raise ValueError(f"Equity curve entry missing timestamp: {entry!r}")
        ts_str = str(ts)
        dt = _parse_timestamp(ts_str)
        normalised.append((dt, ts_str, _coerce_float(equity)))
    normalised.sort(key=lambda item: item[0])
    return normalised


def _load_strategy_series(path: Path) -> Tuple[StrategyManifest, List[Tuple[datetime, str, float]]]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    manifest_path_value = payload.get("manifest_path")
    manifest_id = payload.get("manifest_id")
    if not manifest_path_value:
        raise ValueError(f"metrics file {path} missing manifest_path")
    manifest_path = Path(manifest_path_value)
    if not manifest_path.is_absolute():
        manifest_path = (path.parent / manifest_path).resolve()
    manifest = load_manifest(str(manifest_path))
    if manifest_id and manifest.id != manifest_id:
        raise ValueError(
            f"Manifest id mismatch for {path}: metrics={manifest_id} manifest={manifest.id}"
        )
    curve = payload.get("equity_curve")
    if not isinstance(curve, Sequence) or not curve:
        raise ValueError(f"metrics file {path} missing equity_curve entries")
    return manifest, _normalise_equity_curve(curve)


def _aggregate_equity_curves(curves: Mapping[str, List[Tuple[datetime, str, float]]]) -> List[Tuple[datetime, str, float]]:
    if not curves:
        return []
    timeline_set = {point[0] for series in curves.values() for point in series}
    ts_label: Dict[datetime, str] = {}
    for series in curves.values():
        for dt, label, _ in series:
            ts_label.setdefault(dt, label)
    timeline = sorted(timeline_set)
    index_map: Dict[str, int] = {key: 0 for key in curves}
    last_values: Dict[str, float] = {key: None for key in curves}
    aggregated: List[Tuple[datetime, str, float]] = []
    for dt in timeline:
        total = 0.0
        for key, series in curves.items():
            idx = index_map[key]
            while idx < len(series) and series[idx][0] <= dt:
                last_values[key] = series[idx][2]
                idx += 1
            index_map[key] = idx
            value = last_values[key]
            if value is None:
                raise ValueError(
                    f"Equity curve for {key} missing value on or before {ts_label[dt]}"
                )
            total += value
        aggregated.append((dt, ts_label[dt], total))
    return aggregated


def _max_drawdown(points: Sequence[Tuple[datetime, str, float]]) -> Dict[str, Any]:
    if not points:
        return {"max_drawdown_pct": 0.0}
    peak_value = points[0][2]
    peak_ts = points[0][1]
    peak_dt = points[0][0]
    max_dd = 0.0
    trough_ts = points[0][1]
    trough_dt = points[0][0]
    trough_value = points[0][2]
    for dt, label, value in points:
        if value >= peak_value:
            peak_value = value
            peak_ts = label
            peak_dt = dt
        if peak_value <= 0:
            continue
        drawdown = (peak_value - value) / peak_value
        if drawdown > max_dd:
            max_dd = drawdown
            trough_ts = label
            trough_dt = dt
            trough_value = value
    return {
        "max_drawdown_pct": max_dd * 100.0,
        "peak_ts": peak_ts,
        "peak_dt": peak_dt.isoformat(),
        "peak_equity": peak_value,
        "trough_ts": trough_ts,
        "trough_dt": trough_dt.isoformat(),
        "trough_equity": trough_value,
    }


def _serialise_category_summary(portfolio: PortfolioState) -> List[Dict[str, Any]]:
    categories = sorted(
        set(portfolio.category_utilisation_pct)
        | set(portfolio.category_caps_pct)
        | set(portfolio.category_headroom_pct)
    )
    summary: List[Dict[str, Any]] = []
    for category in categories:
        usage = float(portfolio.category_utilisation_pct.get(category, 0.0))
        cap = portfolio.category_caps_pct.get(category)
        headroom = portfolio.category_headroom_pct.get(category)
        utilisation_ratio = None
        if cap is not None:
            if headroom is None:
                headroom = cap - usage
            if cap > 0:
                utilisation_ratio = usage / cap
        summary.append(
            {
                "category": category,
                "utilisation_pct": usage,
                "cap_pct": cap,
                "headroom_pct": headroom,
                "utilisation_ratio": utilisation_ratio,
            }
        )
    return summary


def _serialise_correlation(portfolio: PortfolioState) -> List[Dict[str, Any]]:
    heatmap: List[Dict[str, Any]] = []
    seen_pairs = set()
    for source, mapping in portfolio.strategy_correlations.items():
        if not isinstance(mapping, Mapping):
            continue
        for target, value in mapping.items():
            pair = tuple(sorted((source, str(target))))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            try:
                corr = float(value)
            except (TypeError, ValueError):
                continue
            if source == target:
                continue
            heatmap.append({"source": source, "target": str(target), "correlation": corr})
    heatmap.sort(key=lambda row: (row["source"], row["target"]))
    return heatmap


def load_portfolio_snapshot(base_dir: Path) -> Tuple[List[StrategySeries], PortfolioTelemetry]:
    telemetry_path = base_dir / "telemetry.json"
    if not telemetry_path.exists():
        raise FileNotFoundError(f"telemetry snapshot not found at {telemetry_path}")
    with telemetry_path.open("r", encoding="utf-8") as handle:
        telemetry_payload = json.load(handle)
    telemetry = PortfolioTelemetry(**telemetry_payload)

    metrics_dir = base_dir / "metrics"
    if not metrics_dir.exists():
        raise FileNotFoundError(f"metrics directory not found at {metrics_dir}")
    series: List[StrategySeries] = []
    for path in sorted(metrics_dir.glob("*.json")):
        manifest, curve = _load_strategy_series(path)
        series.append(StrategySeries(manifest=manifest, equity_curve=curve))
    if not series:
        raise ValueError(f"No metrics files discovered under {metrics_dir}")
    return series, telemetry


def build_portfolio_summary(
    base_dir: Path,
    *,
    generated_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    strategies, telemetry = load_portfolio_snapshot(base_dir)
    manifests = [item.manifest for item in strategies]
    portfolio = build_portfolio_state(manifests, telemetry=telemetry)

    series_map = {item.manifest.id: item.equity_curve for item in strategies}
    aggregate_curve = _aggregate_equity_curves(series_map)

    per_strategy_drawdowns: Dict[str, Dict[str, Any]] = {}
    for item in strategies:
        per_strategy_drawdowns[item.manifest.id] = _max_drawdown(item.equity_curve)

    aggregate_drawdown = _max_drawdown(aggregate_curve)

    if generated_at is None:
        generated_at = datetime.now(timezone.utc)

    gross_cap = portfolio.gross_exposure_cap_pct
    gross_current = portfolio.gross_exposure_pct
    gross_headroom = portfolio.gross_exposure_headroom_pct

    return {
        "generated_at": generated_at.isoformat(),
        "input_dir": str(base_dir),
        "strategies": [
            {
                "manifest_id": item.manifest.id,
                "name": item.manifest.name,
                "category": item.manifest.category,
                "tags": list(item.manifest.tags),
                "max_concurrent_positions": item.manifest.risk.max_concurrent_positions,
                "risk_per_trade_pct": item.manifest.risk.risk_per_trade_pct,
            }
            for item in strategies
        ],
        "category_utilisation": _serialise_category_summary(portfolio),
        "gross_exposure": {
            "current_pct": gross_current,
            "cap_pct": gross_cap,
            "headroom_pct": gross_headroom,
        },
        "correlation_heatmap": _serialise_correlation(portfolio),
        "execution_health": portfolio.execution_health,
        "drawdowns": {
            "aggregate": aggregate_drawdown,
            "per_strategy": per_strategy_drawdowns,
        },
        "aggregate_equity_curve": [
            {"ts": label, "equity": value} for _, label, value in aggregate_curve
        ],
    }


__all__ = [
    "StrategySeries",
    "load_portfolio_snapshot",
    "build_portfolio_summary",
]
