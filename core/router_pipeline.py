from __future__ import annotations

"""Utilities for assembling router portfolio state from runtime telemetry."""

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

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
    correlation_meta: Dict[str, Dict[str, Dict[str, Any]]] = field(default_factory=dict)
    execution_health: Dict[str, Dict[str, float]] = field(default_factory=dict)
    correlation_window_minutes: Optional[float] = None


def _to_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalise_numeric_map(snapshot_map: Mapping[Any, Any]) -> Dict[str, float]:
    """Convert telemetry-style mappings into string→float dictionaries."""

    normalised: Dict[str, float] = {}
    for key, value in snapshot_map.items():
        value_float = _to_float(value)
        if value_float is None:
            continue
        normalised[str(key)] = value_float
    return normalised


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
    category_usage = _normalise_numeric_map(snapshot.category_utilisation_pct)
    category_caps = _normalise_numeric_map(snapshot.category_caps_pct)
    category_budget = _normalise_numeric_map(snapshot.category_budget_pct)
    telemetry_category_budget: Dict[str, float] = dict(category_budget)
    category_budget_headroom = _normalise_numeric_map(
        snapshot.category_budget_headroom_pct
    )

    correlations, correlation_meta = build_correlation_maps(
        snapshot, manifest_index, category_budget
    )

    execution_health: Dict[str, Dict[str, float]] = {}
    for key, value in snapshot.execution_health.items():
        if not isinstance(value, Mapping):
            continue
        inner = _normalise_numeric_map(value)
        if inner:
            execution_health[str(key)] = inner

    (
        exposures,
        category_headroom,
        category_budget_headroom,
    ) = _accumulate_exposures_and_headroom(
        manifest_list,
        absolute_active_counts,
        category_usage,
        category_caps,
        category_budget,
        telemetry_category_budget,
        category_budget_headroom,
    )

    (
        gross_exposure_pct,
        gross_cap_pct,
        gross_headroom_pct,
    ) = _compute_gross_exposure(snapshot, manifest_list, exposures)

    if runtime_metrics:
        _merge_runtime_execution_health(
            manifest_list, execution_health, runtime_metrics
        )

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


def build_correlation_maps(
    snapshot: PortfolioTelemetry,
    manifest_index: Mapping[str, StrategyManifest],
    category_budget: Mapping[str, float],
) -> Tuple[Dict[str, Dict[str, float]], Dict[str, Dict[str, Dict[str, Any]]]]:
    """Construct correlation value and metadata maps from telemetry snapshots."""

    correlations: Dict[str, Dict[str, float]] = {}
    correlation_meta: Dict[str, Dict[str, Dict[str, Any]]] = {}

    for source_key, mapping in snapshot.correlation_meta.items():
        if not isinstance(mapping, Mapping):
            continue
        inner_meta: Dict[str, Dict[str, Any]] = {}
        for peer_key, peer_meta in mapping.items():
            if not isinstance(peer_meta, Mapping):
                continue
            peer_entry = dict(peer_meta)
            peer_entry.setdefault("strategy_id", str(peer_key))
            if "bucket_category" not in peer_entry and "category" in peer_entry:
                peer_entry["bucket_category"] = peer_entry["category"]
            if (
                "bucket_budget_pct" not in peer_entry
                and "category_budget_pct" in peer_entry
            ):
                peer_entry["bucket_budget_pct"] = peer_entry["category_budget_pct"]
            inner_meta[str(peer_key)] = peer_entry
        if inner_meta:
            correlation_meta[str(source_key)] = inner_meta

    for key, value in snapshot.strategy_correlations.items():
        if not isinstance(value, Mapping):
            continue
        inner: Dict[str, float] = {}
        meta_inner: Dict[str, Dict[str, Any]] = {
            peer: dict(meta)
            for peer, meta in correlation_meta.get(str(key), {}).items()
            if isinstance(meta, Mapping)
        }
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
            meta_entry = meta_inner.get(peer_key, {}).copy()
            meta_entry["strategy_id"] = (
                str(peer_manifest.id) if peer_manifest else peer_key
            )

            if peer_category is not None:
                meta_entry["category"] = peer_category
                meta_entry.setdefault("bucket_category", peer_category)

            if budget_value is not None:
                budget_float = float(budget_value)
                meta_entry["category_budget_pct"] = budget_float
                meta_entry.setdefault("bucket_budget_pct", budget_float)

            if "category" not in meta_entry:
                bucket_category = meta_entry.get("bucket_category")
                if bucket_category is not None:
                    meta_entry["category"] = bucket_category

            if "category_budget_pct" not in meta_entry:
                bucket_budget = _to_float(meta_entry.get("bucket_budget_pct"))
                if bucket_budget is not None:
                    meta_entry["category_budget_pct"] = bucket_budget
            meta_inner[peer_key] = meta_entry
        if inner:
            correlations[str(key)] = inner
            if meta_inner:
                correlation_meta[str(key)] = meta_inner

    return correlations, correlation_meta


def _accumulate_exposures_and_headroom(
    manifest_list: Iterable[StrategyManifest],
    absolute_active_counts: Mapping[str, int],
    category_usage: Dict[str, float],
    category_caps: Dict[str, float],
    category_budget: Dict[str, float],
    telemetry_category_budget: Mapping[str, float],
    category_budget_headroom: Dict[str, float],
) -> Tuple[Dict[str, float], Dict[str, float], Dict[str, float]]:
    """Aggregate per-manifest exposures and compute category headroom values."""

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

    category_headroom: Dict[str, float] = {}
    for category, cap in category_caps.items():
        usage = float(category_usage.get(category, 0.0))
        category_headroom[category] = cap - usage

    tolerance = 1e-9
    for category, budget in list(category_budget.items()):
        usage = float(category_usage.get(category, 0.0))
        expected_headroom = budget - usage
        baseline_budget = telemetry_category_budget.get(category)
        stored_headroom = category_budget_headroom.get(category)
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

    return exposures, category_headroom, category_budget_headroom


def _compute_gross_exposure(
    snapshot: PortfolioTelemetry,
    manifest_list: Iterable[StrategyManifest],
    exposures: Mapping[str, float],
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """Derive gross exposure, cap, and headroom figures."""

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

    gross_headroom_pct: Optional[float] = None
    if gross_cap_pct is not None and gross_exposure_pct is not None:
        gross_headroom_pct = gross_cap_pct - gross_exposure_pct

    return gross_exposure_pct, gross_cap_pct, gross_headroom_pct


def _merge_runtime_execution_health(
    manifest_list: Iterable[StrategyManifest],
    execution_health: Dict[str, Dict[str, float]],
    runtime_metrics: Mapping[str, Mapping[str, Any]],
) -> None:
    """Merge execution health exported by runtime metrics into the snapshot map."""

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


__all__ = [
    "PortfolioTelemetry",
    "manifest_category_budget",
    "build_correlation_maps",
    "build_portfolio_state",
]
