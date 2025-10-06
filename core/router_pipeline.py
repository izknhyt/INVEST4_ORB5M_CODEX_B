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


def _normalise_numeric_mapping(
    mapping: Optional[Mapping[Any, Any]]
) -> Dict[str, float]:
    """Return a mapping with string keys and float values, skipping invalid entries."""

    if not isinstance(mapping, Mapping):
        return {}

    normalised: Dict[str, float] = {}
    for key, value in mapping.items():
        value_float = _to_float(value)
        if value_float is None:
            continue
        normalised[str(key)] = value_float
    return normalised


def _merge_correlation_blocks(
    strategy_correlations: Mapping[Any, Mapping[Any, Any]],
    correlation_meta: Mapping[Any, Mapping[Any, Mapping[str, Any]]],
    manifest_index: Mapping[str, StrategyManifest],
    category_budget: Mapping[str, float],
) -> Tuple[Dict[str, Dict[str, float]], Dict[str, Dict[str, Dict[str, Any]]]]:
    """Normalise correlation data and enrich metadata using manifest context."""

    normalised_meta: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for source_key, mapping in correlation_meta.items():
        if not isinstance(mapping, Mapping):
            continue
        inner_meta: Dict[str, Dict[str, Any]] = {}
        for peer_key, peer_meta in mapping.items():
            if not isinstance(peer_meta, Mapping):
                continue
            entry = dict(peer_meta)
            entry.setdefault("strategy_id", str(peer_key))
            if "bucket_category" not in entry and "category" in entry:
                entry["bucket_category"] = entry["category"]
            if "bucket_budget_pct" not in entry and "category_budget_pct" in entry:
                entry["bucket_budget_pct"] = entry["category_budget_pct"]
            inner_meta[str(peer_key)] = entry
        if inner_meta:
            normalised_meta[str(source_key)] = inner_meta

    correlations: Dict[str, Dict[str, float]] = {}
    enriched_meta: Dict[str, Dict[str, Dict[str, Any]]] = {}

    for source_key, mapping in strategy_correlations.items():
        if not isinstance(mapping, Mapping):
            continue
        source_id = str(source_key)
        source_meta = {
            str(peer): dict(meta)
            for peer, meta in normalised_meta.get(source_id, {}).items()
            if isinstance(meta, Mapping)
        }

        normalised_correlations: Dict[str, float] = {}
        for peer_key, value in mapping.items():
            value_float = _to_float(value)
            if value_float is None:
                continue

            peer_id = str(peer_key)
            normalised_correlations[peer_id] = value_float

            peer_manifest = manifest_index.get(peer_id)
            meta_entry = source_meta.get(peer_id, {}).copy()
            meta_entry["strategy_id"] = (
                str(peer_manifest.id) if peer_manifest is not None else peer_id
            )

            peer_category: Optional[str] = None
            budget_value: Optional[float] = None
            if peer_manifest is not None:
                peer_category = peer_manifest.category
                budget_value = category_budget.get(peer_category)
                if budget_value is None:
                    budget_value = manifest_category_budget(peer_manifest)
                if budget_value is None:
                    cap_value = peer_manifest.router.category_cap_pct
                    if cap_value is not None:
                        budget_value = float(cap_value)

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

            source_meta[peer_id] = meta_entry

        if normalised_correlations:
            correlations[source_id] = normalised_correlations
            if source_meta:
                enriched_meta[source_id] = source_meta

    return correlations, enriched_meta


def _compute_category_headroom(
    *,
    manifests: Iterable[StrategyManifest],
    active_counts: Mapping[str, int],
    category_usage: Mapping[str, float],
    category_caps: Mapping[str, float],
    category_budget: Mapping[str, float],
    baseline_category_budget: Mapping[str, float],
    baseline_budget_headroom: Mapping[str, float],
    gross_exposure_pct: Optional[float],
    gross_cap_pct: Optional[float],
) -> Tuple[
    Dict[str, float],
    Dict[str, float],
    Dict[str, float],
    Dict[str, float],
    Dict[str, float],
    Optional[float],
    Optional[float],
    Optional[float],
]:
    """Compute utilisation and headroom information for categories and gross caps."""

    usage: Dict[str, float] = dict(category_usage)
    caps: Dict[str, float] = dict(category_caps)
    budgets: Dict[str, float] = dict(category_budget)
    budget_headroom: Dict[str, float] = dict(baseline_budget_headroom)

    total_exposure = 0.0
    has_exposure = False

    for manifest in manifests:
        manifest_id = str(manifest.id)
        active_count = abs(active_counts.get(manifest_id, 0))

        usage.setdefault(manifest.category, 0.0)

        if active_count > 0:
            exposure = active_count * float(manifest.risk.risk_per_trade_pct)
            total_exposure += exposure
            has_exposure = True
            usage[manifest.category] = usage.get(manifest.category, 0.0) + exposure

        cap_value = manifest.router.category_cap_pct
        if cap_value is not None:
            cap_float = float(cap_value)
            previous_cap = caps.get(manifest.category)
            caps[manifest.category] = (
                cap_float if previous_cap is None else min(previous_cap, cap_float)
            )

        budget_value: Optional[float] = manifest_category_budget(manifest)
        if budget_value is None:
            budget_value = manifest.router.category_cap_pct
        if budget_value is not None:
            budget_float = float(budget_value)
            previous_budget = budgets.get(manifest.category)
            budgets[manifest.category] = (
                budget_float if previous_budget is None else min(previous_budget, budget_float)
            )

    if gross_exposure_pct is None and has_exposure:
        gross_exposure_pct = total_exposure

    if gross_cap_pct is None:
        gross_caps = [
            _to_float(manifest.router.max_gross_exposure_pct)
            for manifest in manifests
            if manifest.router.max_gross_exposure_pct is not None
        ]
        valid_caps = [cap for cap in gross_caps if cap is not None]
        if valid_caps:
            gross_cap_pct = min(valid_caps)

    category_headroom = {
        category: cap - float(usage.get(category, 0.0))
        for category, cap in caps.items()
    }

    tolerance = 1e-9
    for category, budget in list(budgets.items()):
        usage_value = float(usage.get(category, 0.0))
        expected_headroom = float(budget) - usage_value
        baseline_budget_value = baseline_category_budget.get(category)
        baseline_headroom_value = baseline_budget_headroom.get(category)
        baseline_differs = (
            baseline_budget_value is None
            or abs(float(baseline_budget_value) - float(budget)) > tolerance
        )
        headroom_mismatch = (
            baseline_headroom_value is None
            or abs(float(baseline_headroom_value) - expected_headroom) > tolerance
        )
        if baseline_differs or headroom_mismatch:
            budget_headroom[category] = expected_headroom

    gross_headroom_pct: Optional[float] = None
    if gross_cap_pct is not None and gross_exposure_pct is not None:
        gross_headroom_pct = gross_cap_pct - gross_exposure_pct

    return (
        usage,
        caps,
        budgets,
        category_headroom,
        budget_headroom,
        gross_exposure_pct,
        gross_cap_pct,
        gross_headroom_pct,
    )


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
    manifest_index = {str(manifest.id): manifest for manifest in manifest_list}

    active_positions: Dict[str, int] = {
        str(key): int(value) for key, value in snapshot.active_positions.items()
    }
    absolute_active_counts: Dict[str, int] = {
        key: abs(count) for key, count in active_positions.items()
    }
    category_usage = _normalise_numeric_mapping(snapshot.category_utilisation_pct)
    category_caps = _normalise_numeric_mapping(snapshot.category_caps_pct)
    category_budget = _normalise_numeric_mapping(snapshot.category_budget_pct)
    telemetry_category_budget = dict(category_budget)
    category_budget_headroom = _normalise_numeric_mapping(
        snapshot.category_budget_headroom_pct
    )

    gross_exposure_pct = _to_float(snapshot.gross_exposure_pct)
    gross_cap_pct = _to_float(snapshot.gross_exposure_cap_pct)

    (
        category_usage,
        category_caps,
        category_budget,
        category_headroom,
        category_budget_headroom,
        gross_exposure_pct,
        gross_cap_pct,
        gross_headroom_pct,
    ) = _compute_category_headroom(
        manifests=manifest_list,
        active_counts=absolute_active_counts,
        category_usage=category_usage,
        category_caps=category_caps,
        category_budget=category_budget,
        baseline_category_budget=telemetry_category_budget,
        baseline_budget_headroom=category_budget_headroom,
        gross_exposure_pct=gross_exposure_pct,
        gross_cap_pct=gross_cap_pct,
    )

    correlations, correlation_meta = _merge_correlation_blocks(
        snapshot.strategy_correlations,
        snapshot.correlation_meta,
        manifest_index,
        category_budget,
    )

    execution_health: Dict[str, Dict[str, float]] = {
        str(key): inner
        for key, value in snapshot.execution_health.items()
        if (inner := _normalise_numeric_mapping(value))
    }

    if runtime_metrics:
        for manifest in manifest_list:
            metrics = runtime_metrics.get(manifest.id)
            if not metrics:
                continue
            health = metrics.get("execution_health")
            merged_metrics = _normalise_numeric_mapping(health)
            if not merged_metrics:
                continue
            manifest_id = str(manifest.id)
            target = execution_health.get(manifest_id, {}).copy()
            target.update(merged_metrics)
            execution_health[manifest_id] = target

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
