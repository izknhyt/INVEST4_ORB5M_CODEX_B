from __future__ import annotations

"""Strategy router helpers driven by manifest metadata."""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from configs.strategies.loader import StrategyManifest


logger = logging.getLogger(__name__)


@dataclass
class PortfolioState:
    category_utilisation_pct: Dict[str, float] = field(default_factory=dict)
    active_positions: Dict[str, int] = field(default_factory=dict)
    category_caps_pct: Dict[str, float] = field(default_factory=dict)
    gross_exposure_pct: Optional[float] = None
    gross_exposure_cap_pct: Optional[float] = None
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
    active_count = abs(active)
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


def _check_execution_health(manifest: StrategyManifest, portfolio: PortfolioState) -> List[str]:
    health = portfolio.execution_health.get(manifest.id, {})
    reasons: List[str] = []
    if health:
        reject = health.get("reject_rate")
        if (
            reject is not None
            and manifest.router.max_reject_rate is not None
            and float(reject) > manifest.router.max_reject_rate
        ):
            reasons.append(
                f"reject_rate {float(reject):.3f} > max {manifest.router.max_reject_rate:.3f}"
            )
        slip = health.get("slippage_bps")
        if (
            slip is not None
            and manifest.router.max_slippage_bps is not None
            and float(slip) > manifest.router.max_slippage_bps
        ):
            reasons.append(
                f"slippage {float(slip):.1f}bps > max {manifest.router.max_slippage_bps:.1f}bps"
            )
    return reasons


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
            health_reasons = _check_execution_health(manifest, portfolio)
            if health_reasons:
                eligible = False
                reasons.extend(health_reasons)

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

        # Apply soft penalties (do not flip eligibility) when information exists.
        corr_penalty = _max_correlation(manifest, portfolio) if portfolio else None
        if corr_penalty is not None and manifest.router.max_correlation is not None:
            excess = max(0.0, corr_penalty - manifest.router.max_correlation)
            if excess > 0:
                score -= excess
        if portfolio:
            health = portfolio.execution_health.get(manifest.id, {})
            reject = health.get("reject_rate")
            if (
                reject is not None
                and manifest.router.max_reject_rate is not None
                and float(reject) <= manifest.router.max_reject_rate
            ):
                score += 0.01  # small incentive when within guard

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
