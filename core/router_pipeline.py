from __future__ import annotations

"""Utilities for assembling router portfolio state from runtime telemetry."""

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Mapping, Optional

from configs.strategies.loader import StrategyManifest
from router.router_v1 import PortfolioState


@dataclass
class PortfolioTelemetry:
    """Snapshot of live portfolio data consumed by the router pipeline."""

    active_positions: Dict[str, int] = field(default_factory=dict)
    category_utilisation_pct: Dict[str, float] = field(default_factory=dict)
    category_caps_pct: Dict[str, float] = field(default_factory=dict)
    category_budget_pct: Dict[str, float] = field(default_factory=dict)
    category_budget_headroom_pct: Dict[str, float] = field(default_factory=dict)
    gross_exposure_pct: Optional[float] = None
    gross_exposure_cap_pct: Optional[float] = None
    strategy_correlations: Dict[str, Dict[str, float]] = field(default_factory=dict)
    execution_health: Dict[str, Dict[str, float]] = field(default_factory=dict)
    correlation_window_minutes: Optional[float] = None


def _to_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def manifest_category_budget(manifest: StrategyManifest) -> Optional[float]:
    """Return the governance budget declared for a manifest's category."""

    budget = manifest.router.category_budget_pct
    if budget is not None:
        return float(budget)

    raw_block = manifest.raw.get("governance") if isinstance(manifest.raw, Mapping) else None
    if isinstance(raw_block, Mapping):
        value = _to_float(raw_block.get("category_budget_pct"))
        if value is not None:
            return value

    return None


def build_portfolio_state(
    manifests: Iterable[StrategyManifest],
    *,
    telemetry: Optional[PortfolioTelemetry] = None,
    runtime_metrics: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> PortfolioState:
    """Construct a :class:`PortfolioState` from manifests and live telemetry.

    Parameters
    ----------
    manifests:
        Strategy manifests that contribute to the portfolio. The function will
        use their risk metadata to infer utilisation and category limits when
        explicit telemetry is missing.
    telemetry:
        Optional snapshot populated with live counts (active positions,
        category utilisation, correlation matrices, etc.).
    runtime_metrics:
        Optional mapping keyed by manifest ID with runtime exports from
        :class:`core.runner.BacktestRunner`. When provided the execution
        health block is merged so the router can gate on reject rates and
        slippage guards.
    """

    snapshot = telemetry or PortfolioTelemetry()
    manifest_list = list(manifests)
    manifest_index = {manifest.id: manifest for manifest in manifest_list}

    active_positions: Dict[str, int] = {
        str(key): int(value) for key, value in snapshot.active_positions.items()
    }
    absolute_active_counts: Dict[str, int] = {
        key: abs(count) for key, count in active_positions.items()
    }
    category_usage: Dict[str, float] = {}
    for key, value in snapshot.category_utilisation_pct.items():
        value_float = _to_float(value)
        if value_float is None:
            continue
        category_usage[str(key)] = value_float

    category_caps: Dict[str, float] = {}
    for key, value in snapshot.category_caps_pct.items():
        value_float = _to_float(value)
        if value_float is None:
            continue
        category_caps[str(key)] = value_float

    category_budget: Dict[str, float] = {}
    for key, value in snapshot.category_budget_pct.items():
        value_float = _to_float(value)
        if value_float is None:
            continue
        category_budget[str(key)] = value_float

    telemetry_category_budget: Dict[str, float] = dict(category_budget)

    category_budget_headroom: Dict[str, float] = {}
    for key, value in snapshot.category_budget_headroom_pct.items():
        value_float = _to_float(value)
        if value_float is None:
            continue
        category_budget_headroom[str(key)] = value_float

    correlations: Dict[str, Dict[str, float]] = {}
    correlation_meta: Dict[str, Dict[str, Dict[str, Optional[float]]]] = {}
    for key, value in snapshot.strategy_correlations.items():
        inner: Dict[str, float] = {}
        meta_inner: Dict[str, Dict[str, Optional[float]]] = {}
        for inner_k, inner_v in value.items():
            inner_float = _to_float(inner_v)
            if inner_float is None:
                continue
            peer_key = str(inner_k)
            inner[peer_key] = inner_float
            peer_manifest = manifest_index.get(peer_key)
            budget_value: Optional[float] = None
            peer_category: Optional[str] = None
            if peer_manifest is not None:
                peer_category = peer_manifest.category
                budget_value = category_budget.get(peer_category)
                if budget_value is None:
                    budget_value = manifest_category_budget(peer_manifest)
                if budget_value is None:
                    cap_value = peer_manifest.router.category_cap_pct
                    if cap_value is not None:
                        budget_value = float(cap_value)
            meta_inner[peer_key] = {
                "strategy_id": str(peer_manifest.id) if peer_manifest else peer_key,
                "category": peer_category,
                "category_budget_pct": float(budget_value) if budget_value is not None else None,
            }
        if inner:
            correlations[str(key)] = inner
            if meta_inner:
                correlation_meta[str(key)] = meta_inner

    execution_health: Dict[str, Dict[str, float]] = {}
    for key, value in snapshot.execution_health.items():
        inner: Dict[str, float] = {}
        for inner_k, inner_v in value.items():
            inner_float = _to_float(inner_v)
            if inner_float is None:
                continue
            inner[str(inner_k)] = inner_float
        if inner:
            execution_health[str(key)] = inner

    exposures: Dict[str, float] = {}
    for manifest in manifest_list:
        active_count = absolute_active_counts.get(manifest.id, 0)
        if active_count > 0:
            exposure = active_count * float(manifest.risk.risk_per_trade_pct)
            exposures[manifest.id] = exposures.get(manifest.id, 0.0) + exposure
            category_usage[manifest.category] = (
                category_usage.get(manifest.category, 0.0) + exposure
            )
        cap_value = manifest.router.category_cap_pct
        if cap_value is not None:
            cap_float = float(cap_value)
            prev_cap = category_caps.get(manifest.category)
            category_caps[manifest.category] = (
                cap_float if prev_cap is None else min(prev_cap, cap_float)
            )
        budget_value = manifest_category_budget(manifest)
        if budget_value is None:
            budget_value = manifest.router.category_cap_pct
        if budget_value is not None:
            budget_float = float(budget_value)
            prev_budget = category_budget.get(manifest.category)
            category_budget[manifest.category] = (
                budget_float if prev_budget is None else min(prev_budget, budget_float)
            )
        category_usage.setdefault(manifest.category, 0.0)

    gross_exposure_pct = _to_float(snapshot.gross_exposure_pct)
    if gross_exposure_pct is None and exposures:
        gross_exposure_pct = sum(exposures.values())

    gross_cap_pct = _to_float(snapshot.gross_exposure_cap_pct)
    if gross_cap_pct is None:
        gross_caps = [
            _to_float(manifest.router.max_gross_exposure_pct)
            for manifest in manifest_list
            if manifest.router.max_gross_exposure_pct is not None
        ]
        gross_caps = [cap for cap in gross_caps if cap is not None]
        if gross_caps:
            gross_cap_pct = min(gross_caps)

    category_headroom: Dict[str, float] = {}
    for category, cap in category_caps.items():
        usage = float(category_usage.get(category, 0.0))
        category_headroom[category] = cap - usage

    for category, budget in list(category_budget.items()):
        if budget is None:
            category_budget.pop(category, None)
            continue
        usage = float(category_usage.get(category, 0.0))
        expected_headroom = budget - usage
        baseline_budget = telemetry_category_budget.get(category)
        stored_headroom = category_budget_headroom.get(category)
        tolerance = 1e-9
        baseline_differs = (
            baseline_budget is None
            or abs(float(baseline_budget) - budget) > tolerance
        )
        headroom_mismatch = (
            stored_headroom is None
            or abs(float(stored_headroom) - expected_headroom) > tolerance
        )
        if baseline_differs or headroom_mismatch:
            category_budget_headroom[category] = expected_headroom

    gross_headroom_pct: Optional[float] = None
    if gross_cap_pct is not None and gross_exposure_pct is not None:
        gross_headroom_pct = gross_cap_pct - gross_exposure_pct

    if runtime_metrics:
        for manifest in manifest_list:
            metrics = runtime_metrics.get(manifest.id)
            if not metrics:
                continue
            health = metrics.get("execution_health")
            if not isinstance(health, Mapping):
                continue
            target = execution_health.get(manifest.id, {}).copy()
            for inner_metric, inner_value in health.items():
                metric_value = _to_float(inner_value)
                if metric_value is None:
                    continue
                target[str(inner_metric)] = metric_value
            if target:
                execution_health[manifest.id] = target

    correlation_window_minutes = _to_float(snapshot.correlation_window_minutes)

    return PortfolioState(
        category_utilisation_pct=category_usage,
        active_positions=active_positions,
        category_caps_pct=category_caps,
        category_headroom_pct=category_headroom,
        category_budget_pct=category_budget,
        category_budget_headroom_pct=category_budget_headroom,
        gross_exposure_pct=gross_exposure_pct,
        gross_exposure_cap_pct=gross_cap_pct,
        gross_exposure_headroom_pct=gross_headroom_pct,
        strategy_correlations=correlations,
        correlation_meta=correlation_meta,
        execution_health=execution_health,
        correlation_window_minutes=correlation_window_minutes,
    )


__all__ = [
    "PortfolioTelemetry",
    "manifest_category_budget",
    "build_portfolio_state",
]
