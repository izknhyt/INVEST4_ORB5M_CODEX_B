from __future__ import annotations

"""Strategy router helpers driven by manifest metadata."""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

from configs.strategies.loader import StrategyManifest


logger = logging.getLogger(__name__)


@dataclass
class PortfolioState:
    category_utilisation_pct: Dict[str, float] = field(default_factory=dict)
    active_positions: Dict[str, int] = field(default_factory=dict)
    category_caps_pct: Dict[str, float] = field(default_factory=dict)
    category_headroom_pct: Dict[str, float] = field(default_factory=dict)
    category_budget_pct: Dict[str, float] = field(default_factory=dict)
    category_budget_headroom_pct: Dict[str, float] = field(default_factory=dict)
    gross_exposure_pct: Optional[float] = None
    gross_exposure_cap_pct: Optional[float] = None
    gross_exposure_headroom_pct: Optional[float] = None
    strategy_correlations: Dict[str, Dict[str, float]] = field(default_factory=dict)
    execution_health: Dict[str, Dict[str, float]] = field(default_factory=dict)


@dataclass
class SelectionResult:
    manifest_id: str
    eligible: bool
    score: float
    reasons: List[str]
    manifest: StrategyManifest

    def as_dict(self) -> Dict[str, Any]:
        return {
            "manifest_id": self.manifest_id,
            "eligible": self.eligible,
            "score": self.score,
            "reasons": self.reasons,
            "category": self.manifest.category,
            "tags": list(self.manifest.tags),
        }


@dataclass
class ExecutionMetricResult:
    """Structured outcome for a single execution-health metric."""

    metric: str
    value: float
    guard: float
    ratio: Optional[float]
    score_delta: float
    disqualified: bool
    message: str


@dataclass
class ExecutionHealthStatus:
    """Outcome of execution-health evaluation for a candidate."""

    disqualifying_reasons: List[str] = field(default_factory=list)
    log_messages: List[str] = field(default_factory=list)
    score_delta: float = 0.0
    penalties: Dict[str, float] = field(default_factory=dict)
    metric_results: List[ExecutionMetricResult] = field(default_factory=list)


def _session_allowed(manifest: StrategyManifest, session: Optional[str]) -> bool:
    sessions = manifest.router.allowed_sessions
    if not sessions or session is None:
        return True
    return session.upper() in sessions


def _band_allowed(allowed: Iterable[str], value: Optional[str]) -> bool:
    allowed = tuple(x.lower() for x in allowed)
    if not allowed or value is None:
        return True
    return value.lower() in allowed


def _check_category_cap(manifest: StrategyManifest, portfolio: PortfolioState) -> Optional[str]:
    category = manifest.category
    usage = float(portfolio.category_utilisation_pct.get(category, 0.0))
    cap = manifest.router.category_cap_pct
    if cap is None:
        cap = portfolio.category_caps_pct.get(category)
    if cap is None:
        return None
    if usage >= cap:
        return f"category utilisation {usage:.1f}% >= cap {cap:.1f}%"
    return None


def _check_concurrency(manifest: StrategyManifest, portfolio: PortfolioState) -> Optional[str]:
    limit = manifest.risk.max_concurrent_positions
    if limit <= 0:
        return "max_concurrent_positions set to non-positive value"
    active = portfolio.active_positions.get(manifest.id, 0)
    try:
        active_int = int(active)
    except (TypeError, ValueError):
        active_int = 0
    active_count = abs(active_int)
    if active_count >= limit:
        return f"active positions {active_count} >= limit {limit}"
    return None


def _check_gross_exposure(manifest: StrategyManifest, portfolio: PortfolioState) -> Optional[str]:
    current = portfolio.gross_exposure_pct
    if current is None:
        return None
    cap = manifest.router.max_gross_exposure_pct
    if cap is None:
        cap = portfolio.gross_exposure_cap_pct
    if cap is None:
        return None
    if current >= cap:
        return f"gross exposure {current:.1f}% >= cap {cap:.1f}%"
    return None


def _to_optional_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _resolve_category_headroom(
    manifest: StrategyManifest, portfolio: PortfolioState
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    category = manifest.category
    usage = _to_optional_float(portfolio.category_utilisation_pct.get(category))
    manifest_cap = _to_optional_float(manifest.router.category_cap_pct)
    fallback_cap = _to_optional_float(portfolio.category_caps_pct.get(category))
    cap = manifest_cap if manifest_cap is not None else fallback_cap
    headroom = _to_optional_float(portfolio.category_headroom_pct.get(category))
    if headroom is None and usage is not None and cap is not None:
        headroom = cap - usage
    return usage, cap, headroom


def _resolve_category_budget(
    manifest: StrategyManifest, portfolio: PortfolioState
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    category = manifest.category
    usage = _to_optional_float(portfolio.category_utilisation_pct.get(category))
    budget = _to_optional_float(portfolio.category_budget_pct.get(category))
    if budget is None:
        budget = _to_optional_float(manifest.router.category_budget_pct)
    if budget is None:
        budget = _to_optional_float(manifest.router.category_cap_pct)
    headroom = _to_optional_float(
        portfolio.category_budget_headroom_pct.get(category)
    )
    if headroom is None and usage is not None and budget is not None:
        headroom = budget - usage
    return usage, budget, headroom


def _resolve_gross_headroom(
    manifest: StrategyManifest, portfolio: PortfolioState
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    usage = _to_optional_float(portfolio.gross_exposure_pct)
    manifest_cap = _to_optional_float(manifest.router.max_gross_exposure_pct)
    fallback_cap = _to_optional_float(portfolio.gross_exposure_cap_pct)
    cap = manifest_cap if manifest_cap is not None else fallback_cap
    headroom = _to_optional_float(portfolio.gross_exposure_headroom_pct)
    if headroom is None and usage is not None and cap is not None:
        headroom = cap - usage
    return usage, cap, headroom


def _headroom_score_adjustment(headroom: Optional[float]) -> float:
    if headroom is None:
        return 0.0
    if headroom <= 5.0:
        return -0.5
    if headroom <= 10.0:
        return -0.2
    if headroom >= 35.0:
        return 0.2
    if headroom >= 20.0:
        return 0.1
    return 0.0


def _budget_score_adjustment(
    budget_headroom: Optional[float], cap_headroom: Optional[float]
) -> float:
    if budget_headroom is None or budget_headroom >= 0:
        return 0.0
    overage = abs(budget_headroom)
    if overage <= 2.0:
        penalty = -0.10
    elif overage <= 5.0:
        penalty = -0.25
    elif overage <= 10.0:
        penalty = -0.40
    else:
        penalty = -0.60
    if cap_headroom is not None and cap_headroom <= 5.0:
        penalty -= 0.10
    return penalty


def _format_headroom_reason(
    label: str,
    usage: Optional[float],
    cap: Optional[float],
    headroom: Optional[float],
    delta: float,
) -> str:
    details: List[str] = []
    if headroom is not None:
        details.append(f"headroom={headroom:.1f}%")
    if usage is not None:
        details.append(f"usage={usage:.1f}%")
    if cap is not None:
        details.append(f"cap={cap:.1f}%")
    if delta != 0:
        details.append(f"score_delta={delta:+.2f}")
    else:
        details.append("score_delta=+0.00")
    joined = ", ".join(details)
    return f"{label} headroom ({joined})"


def _max_correlation(manifest: StrategyManifest, portfolio: PortfolioState) -> Optional[float]:
    corr_map: Dict[str, float] = {}
    if manifest.id in portfolio.strategy_correlations:
        corr_map.update(portfolio.strategy_correlations.get(manifest.id, {}))
    for tag in manifest.router.correlation_tags:
        corr_map.update(portfolio.strategy_correlations.get(tag, {}))
    if not corr_map:
        return None
    return max(abs(float(val)) for val in corr_map.values())


def _check_correlation(manifest: StrategyManifest, portfolio: PortfolioState) -> Optional[str]:
    limit = manifest.router.max_correlation
    if limit is None:
        return None
    max_corr = _max_correlation(manifest, portfolio)
    if max_corr is None:
        return None
    if max_corr > limit:
        return f"correlation {max_corr:.2f} exceeds cap {limit:.2f}"
    return None


def _execution_health_score_adjustment(ratio: float) -> float:
    """Return a score delta based on how close a metric ratio is to its guard."""

    if ratio <= 0.5:
        return 0.05
    if ratio <= 0.75:
        return 0.02
    if ratio <= 0.9:
        return 0.0
    if ratio <= 0.97:
        return -0.05
    return -0.15


def _format_metric_value(metric: str, value: float) -> str:
    fmt = "{:.3f}" if metric == "reject_rate" else "{:.1f}"
    unit = "" if metric == "reject_rate" else "bps"
    return f"{fmt.format(value)}{unit}"


def _format_execution_reason(
    metric: str,
    value: float,
    guard: float,
    ratio: Optional[float],
    delta: float,
) -> str:
    parts = [
        f"value={_format_metric_value(metric, value)}",
        f"guard={_format_metric_value(metric, guard)}",
    ]
    if ratio is not None:
        parts.append(f"ratio={ratio:.2f}")
    parts.append(f"score_delta={delta:+.2f}")
    joined = ", ".join(parts)
    return f"execution {metric} ({joined})"


def _evaluate_execution_metric(
    metric: str, value: float, guard: float
) -> ExecutionMetricResult:
    """Evaluate a single execution metric against its guard threshold."""

    if guard <= 0:
        message = _format_execution_reason(metric, value, guard, None, 0.0)
        disqualified = value > guard
        return ExecutionMetricResult(
            metric=metric,
            value=value,
            guard=guard,
            ratio=None,
            score_delta=0.0,
            disqualified=disqualified,
            message=message,
        )

    ratio = value / guard
    if ratio > 1.0:
        message = _format_execution_reason(metric, value, guard, ratio, 0.0)
        return ExecutionMetricResult(
            metric=metric,
            value=value,
            guard=guard,
            ratio=ratio,
            score_delta=0.0,
            disqualified=True,
            message=message,
        )

    delta = _execution_health_score_adjustment(ratio)
    message = _format_execution_reason(metric, value, guard, ratio, delta)
    return ExecutionMetricResult(
        metric=metric,
        value=value,
        guard=guard,
        ratio=ratio,
        score_delta=delta,
        disqualified=False,
        message=message,
    )


def _check_execution_health(
    manifest: StrategyManifest, portfolio: PortfolioState
) -> ExecutionHealthStatus:
    health = portfolio.execution_health.get(manifest.id, {})
    status = ExecutionHealthStatus()
    if not health:
        return status

    metrics: Tuple[Tuple[str, Optional[float], Optional[float]], ...] = (
        (
            "reject_rate",
            _to_optional_float(health.get("reject_rate")),
            _to_optional_float(manifest.router.max_reject_rate),
        ),
        (
            "slippage_bps",
            _to_optional_float(health.get("slippage_bps")),
            _to_optional_float(manifest.router.max_slippage_bps),
        ),
    )

    for metric, value, guard in metrics:
        if value is None or guard is None:
            continue
        result = _evaluate_execution_metric(metric, value, guard)
        status.metric_results.append(result)
        status.log_messages.append(result.message)
        if result.disqualified:
            status.disqualifying_reasons.append(result.message)
            status.penalties[metric] = 0.0
            continue
        status.penalties[metric] = result.score_delta
        status.score_delta += result.score_delta

    return status


def select_candidates(
    market_ctx: Dict[str, Any],
    manifests: Iterable[StrategyManifest],
    portfolio: Optional[PortfolioState] = None,
    strategy_signals: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[SelectionResult]:
    """Filter + score manifests using current market/portfolio context."""
    session = market_ctx.get("session")
    spread_band = market_ctx.get("spread_band")
    rv_band = market_ctx.get("rv_band")

    results: List[SelectionResult] = []
    for manifest in manifests:
        reasons: List[str] = []
        eligible = True

        if not _session_allowed(manifest, session):
            eligible = False
            reasons.append(f"session {session} not allowed")

        if not _band_allowed(manifest.router.allow_spread_bands, spread_band):
            eligible = False
            reasons.append(f"spread band {spread_band} not allowed")

        if not _band_allowed(manifest.router.allow_rv_bands, rv_band):
            eligible = False
            reasons.append(f"rv band {rv_band} not allowed")

        health_score_delta = 0.0
        if portfolio is not None:
            cap_reason = _check_category_cap(manifest, portfolio)
            if cap_reason:
                eligible = False
                reasons.append(cap_reason)
            conc_reason = _check_concurrency(manifest, portfolio)
            if conc_reason:
                eligible = False
                reasons.append(conc_reason)
            gross_reason = _check_gross_exposure(manifest, portfolio)
            if gross_reason:
                eligible = False
                reasons.append(gross_reason)
            corr_reason = _check_correlation(manifest, portfolio)
            if corr_reason:
                eligible = False
                reasons.append(corr_reason)
            health_status = _check_execution_health(manifest, portfolio)
            if health_status.disqualifying_reasons:
                eligible = False
                reasons.extend(health_status.disqualifying_reasons)
            for message in health_status.log_messages:
                if message not in reasons:
                    reasons.append(message)
            health_score_delta = health_status.score_delta

        signal_ctx = (strategy_signals or {}).get(manifest.id, {})
        score_value: Optional[float] = None
        if "score" in signal_ctx:
            raw_score = signal_ctx["score"]
            if raw_score is not None:
                score_value = float(raw_score)
        if score_value is None:
            ev_raw = signal_ctx.get("ev_lcb")
            if ev_raw is not None:
                score_value = float(ev_raw)
        score = score_value if score_value is not None else 0.0
        score += manifest.router.priority

        if health_score_delta != 0.0:
            score += health_score_delta

        # Apply soft penalties (do not flip eligibility) when information exists.
        corr_penalty = _max_correlation(manifest, portfolio) if portfolio else None
        if corr_penalty is not None and manifest.router.max_correlation is not None:
            excess = max(0.0, corr_penalty - manifest.router.max_correlation)
            if excess > 0:
                score -= excess
        if portfolio:
            usage, cap, headroom = _resolve_category_headroom(manifest, portfolio)
            if headroom is not None or (usage is not None and cap is not None):
                delta = _headroom_score_adjustment(headroom)
                score += delta
                reasons.append(
                    _format_headroom_reason("category", usage, cap, headroom, delta)
                )
            budget_usage, budget_cap, budget_headroom = _resolve_category_budget(
                manifest, portfolio
            )
            cap_headroom = _to_optional_float(
                portfolio.category_headroom_pct.get(manifest.category)
            )
            if budget_cap is not None or budget_headroom is not None or budget_usage is not None:
                budget_delta = _budget_score_adjustment(
                    budget_headroom, cap_headroom
                )
                score += budget_delta
                reasons.append(
                    _format_headroom_reason(
                        "category budget",
                        budget_usage,
                        budget_cap,
                        budget_headroom,
                        budget_delta,
                    )
                )
            gross_usage, gross_cap, gross_headroom = _resolve_gross_headroom(
                manifest, portfolio
            )
            if gross_headroom is not None or (
                gross_usage is not None and gross_cap is not None
            ):
                gross_delta = _headroom_score_adjustment(gross_headroom)
                score += gross_delta
                reasons.append(
                    _format_headroom_reason(
                        "gross", gross_usage, gross_cap, gross_headroom, gross_delta
                    )
                )
        ev_lcb_raw = signal_ctx.get("ev_lcb")
        if ev_lcb_raw is not None and "ev_lcb" not in reasons:
            try:
                ev_lcb_value = float(ev_lcb_raw)
            except (TypeError, ValueError):
                logger.warning(
                    "Failed to convert ev_lcb=%r for manifest %s", ev_lcb_raw, manifest.id
                )
            else:
                reasons.append(f"ev_lcb={ev_lcb_value:.3f}")

        results.append(SelectionResult(
            manifest_id=manifest.id,
            eligible=eligible,
            score=score,
            reasons=reasons,
            manifest=manifest,
        ))

    results.sort(key=lambda r: (r.eligible, r.score), reverse=True)
    return results


__all__ = [
    "PortfolioState",
    "SelectionResult",
    "select_candidates",
]
