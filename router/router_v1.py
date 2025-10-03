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
    cap = manifest.router.category_cap_pct or portfolio.category_caps_pct.get(category)
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
    if active >= limit:
        return f"active positions {active} >= limit {limit}"
    return None


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

        signal_ctx = (strategy_signals or {}).get(manifest.id, {})
        score = float(signal_ctx.get("score") or signal_ctx.get("ev_lcb") or 0.0)
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
