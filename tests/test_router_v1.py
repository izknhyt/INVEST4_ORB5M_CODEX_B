from pytest import approx

from configs.strategies.loader import load_manifest
from router.router_v1 import (
    PortfolioState,
    _check_execution_health,
    select_candidates,
)


def load_day_manifest():
    return load_manifest("configs/strategies/day_orb_5m.yaml")


def test_session_and_band_filtering():
    manifest = load_day_manifest()
    ctx = {"session": "LDN", "spread_band": "narrow", "rv_band": "high"}
    res = select_candidates(ctx, [manifest])
    assert res[0].eligible is True

    ctx_tokyo = {"session": "TOK", "spread_band": "narrow", "rv_band": "high"}
    res2 = select_candidates(ctx_tokyo, [manifest])
    assert res2[0].eligible is False
    assert any("session" in reason for reason in res2[0].reasons)

    ctx_spread = {"session": "LDN", "spread_band": "wide", "rv_band": "high"}
    res3 = select_candidates(ctx_spread, [manifest])
    assert res3[0].eligible is False
    assert any("spread" in reason for reason in res3[0].reasons)


def test_category_cap_and_concurrency():
    manifest = load_day_manifest()
    portfolio = PortfolioState(
        category_utilisation_pct={"day": 45.0},
        category_caps_pct={"day": 40.0},
        active_positions={manifest.id: manifest.risk.max_concurrent_positions},
    )
    ctx = {"session": "LDN", "spread_band": "narrow", "rv_band": "high"}
    res = select_candidates(ctx, [manifest], portfolio=portfolio)
    assert res[0].eligible is False
    reasons = " ".join(res[0].reasons)
    assert "category utilisation" in reasons
    assert "active positions" in reasons


def test_manifest_category_cap_zero_blocks_positive_usage():
    manifest = load_day_manifest()
    manifest.router.category_cap_pct = 0.0
    portfolio = PortfolioState(
        category_utilisation_pct={manifest.category: 5.0},
        category_caps_pct={manifest.category: 40.0},
    )
    ctx = {"session": "LDN", "spread_band": "narrow", "rv_band": "high"}
    res = select_candidates(ctx, [manifest], portfolio=portfolio)
    assert res[0].eligible is False
    assert any("category utilisation" in reason for reason in res[0].reasons)


def test_scoring_sorting():
    manifest = load_day_manifest()
    ctx = {"session": "LDN", "spread_band": "narrow", "rv_band": "mid"}
    signals = {manifest.id: {"score": 1.5, "ev_lcb": 0.7}}
    res = select_candidates(ctx, [manifest], strategy_signals=signals)
    assert res[0].score == 1.5
    assert any("ev_lcb" in reason for reason in res[0].reasons)


def test_zero_score_respected_when_ev_lcb_present():
    manifest = load_day_manifest()
    manifest.router.priority = 0.0
    ctx = {"session": "LDN", "spread_band": "narrow", "rv_band": "mid"}
    signals = {manifest.id: {"score": 0.0, "ev_lcb": 0.9}}
    res = select_candidates(ctx, [manifest], strategy_signals=signals)
    assert res[0].score == 0.0


def test_zero_score_string_not_overridden_by_ev_lcb():
    manifest = load_day_manifest()
    manifest.router.priority = 0.0
    ctx = {"session": "LDN", "spread_band": "narrow", "rv_band": "mid"}
    signals = {manifest.id: {"score": "0.0", "ev_lcb": -0.4}}
    res = select_candidates(ctx, [manifest], strategy_signals=signals)
    assert res[0].score == 0.0
    assert any("ev_lcb" in reason for reason in res[0].reasons)


def test_gross_exposure_cap_blocks_candidate():
    manifest = load_day_manifest()
    manifest.router.max_gross_exposure_pct = 60.0
    portfolio = PortfolioState(
        category_utilisation_pct={manifest.category: 10.0},
        category_caps_pct={manifest.category: 40.0},
        gross_exposure_pct=72.0,
        gross_exposure_cap_pct=80.0,
    )
    ctx = {"session": "LDN", "spread_band": "narrow", "rv_band": "high"}
    res = select_candidates(ctx, [manifest], portfolio=portfolio)
    assert res[0].eligible is False
    assert any("gross exposure" in reason for reason in res[0].reasons)


def test_correlation_guard_same_bucket_disqualifies():
    manifest = load_day_manifest()
    peer_manifest = load_manifest("configs/strategies/mean_reversion.yaml")
    manifest.router.max_correlation = 0.6
    manifest.router.priority = 0.0
    correlation_value = 0.72
    bucket_budget = 40.0
    portfolio = PortfolioState(
        category_budget_pct={manifest.category: bucket_budget},
        strategy_correlations={
            manifest.id: {peer_manifest.id: correlation_value},
        },
        correlation_meta={
            manifest.id: {
                peer_manifest.id: {
                    "strategy_id": peer_manifest.id,
                    "category": peer_manifest.category,
                    "category_budget_pct": bucket_budget,
                }
            }
        },
    )

    ctx = {"session": "LDN", "spread_band": "narrow", "rv_band": "mid"}
    result = select_candidates(ctx, [manifest], portfolio=portfolio)[0]

    assert result.eligible is False
    correlation_reasons = [r for r in result.reasons if "correlation" in r]
    assert len(correlation_reasons) == 1
    assert "bucket day" in correlation_reasons[0]
    assert f"{correlation_value:.2f}" in correlation_reasons[0]


def test_correlation_guard_cross_bucket_penalises_once():
    manifest = load_day_manifest()
    peer_manifest = load_manifest("configs/strategies/tokyo_micro_mean_reversion.yaml")
    manifest.router.max_correlation = 0.5
    manifest.router.priority = 0.0
    manifest.router.correlation_tags = ("momentum", "asia")
    portfolio = PortfolioState(
        strategy_correlations={
            manifest.id: {peer_manifest.id: 0.8},
            "momentum": {peer_manifest.id: 0.75},
            "asia": {peer_manifest.id: 0.7},
        },
        correlation_meta={
            manifest.id: {
                peer_manifest.id: {
                    "strategy_id": peer_manifest.id,
                    "category": peer_manifest.category,
                    "category_budget_pct": 20.0,
                }
            },
            "momentum": {
                peer_manifest.id: {
                    "strategy_id": peer_manifest.id,
                    "category": peer_manifest.category,
                    "category_budget_pct": 20.0,
                }
            },
            "asia": {
                peer_manifest.id: {
                    "strategy_id": peer_manifest.id,
                    "category": peer_manifest.category,
                    "category_budget_pct": 20.0,
                }
            },
        },
        category_budget_pct={manifest.category: 40.0, peer_manifest.category: 20.0},
    )

    ctx = {"session": "LDN", "spread_band": "narrow", "rv_band": "mid"}
    result = select_candidates(ctx, [manifest], portfolio=portfolio)[0]

    assert result.eligible is True
    correlation_reasons = [r for r in result.reasons if "correlation" in r]
    assert len(correlation_reasons) == 1
    assert "score_delta=-0.30" in correlation_reasons[0]
    assert result.score == approx(-0.30)


def test_execution_health_guard():
    manifest = load_day_manifest()
    manifest.router.max_reject_rate = 0.05
    manifest.router.max_slippage_bps = 8.0
    portfolio = PortfolioState(
        execution_health={manifest.id: {"reject_rate": 0.08, "slippage_bps": 12.0}}
    )
    ctx = {"session": "LDN", "spread_band": "narrow", "rv_band": "mid"}
    res = select_candidates(ctx, [manifest], portfolio=portfolio)
    assert res[0].eligible is False
    joined = " ".join(res[0].reasons)
    assert "reject_rate" in joined
    assert "slippage" in joined
    assert "ratio=" in joined
    assert "margin=-" in joined
    assert any("execution reject_rate" in reason for reason in res[0].reasons)
    assert any("execution slippage_bps" in reason for reason in res[0].reasons)


def test_execution_health_bonus_and_penalty_tiers():
    manifest = load_day_manifest()
    manifest.router.priority = 0.0
    manifest.router.max_reject_rate = 0.05
    manifest.router.max_slippage_bps = 10.0

    ctx = {"session": "LDN", "spread_band": "narrow", "rv_band": "mid"}
    signals = {manifest.id: {"score": 1.0}}

    bonus_state = PortfolioState(
        execution_health={manifest.id: {"reject_rate": 0.015, "slippage_bps": 2.0}}
    )
    penalty_state = PortfolioState(
        execution_health={manifest.id: {"reject_rate": 0.048, "slippage_bps": 9.8}}
    )

    bonus_result = select_candidates(
        ctx, [manifest], portfolio=bonus_state, strategy_signals=signals
    )[0]
    penalty_result = select_candidates(
        ctx, [manifest], portfolio=penalty_state, strategy_signals=signals
    )[0]

    assert bonus_result.eligible is True
    assert bonus_result.score == approx(1.10)
    bonus_joined = " ".join(bonus_result.reasons)
    assert "execution reject_rate" in bonus_joined
    assert "score_delta=+0.05" in bonus_joined
    assert "execution slippage_bps" in bonus_joined
    assert "margin=+" in bonus_joined

    assert penalty_result.eligible is True
    assert penalty_result.score == approx(0.80)
    penalty_joined = " ".join(penalty_result.reasons)
    assert "score_delta=-0.05" in penalty_joined
    assert "score_delta=-0.15" in penalty_joined
    assert "margin=+" in penalty_joined

    bonus_status = _check_execution_health(manifest, bonus_state)
    assert bonus_status.penalties["reject_rate"] == approx(0.05)
    assert bonus_status.penalties["slippage_bps"] == approx(0.05)
    assert bonus_status.score_delta == approx(0.10)
    assert bonus_status.disqualifying_reasons == []
    assert bonus_status.metric_results[0].margin == approx(
        manifest.router.max_reject_rate - bonus_state.execution_health[manifest.id]["reject_rate"]
    )

    penalty_status = _check_execution_health(manifest, penalty_state)
    assert penalty_status.penalties["reject_rate"] == approx(-0.05)
    assert penalty_status.penalties["slippage_bps"] == approx(-0.15)
    assert penalty_status.score_delta == approx(-0.20)
    assert penalty_status.disqualifying_reasons == []
    assert penalty_status.metric_results[0].margin == approx(
        manifest.router.max_reject_rate
        - penalty_state.execution_health[manifest.id]["reject_rate"]
    )


def test_execution_health_disqualification_penalty_payload():
    manifest = load_day_manifest()
    manifest.router.max_reject_rate = 0.05
    manifest.router.max_slippage_bps = 10.0

    fail_state = PortfolioState(
        execution_health={manifest.id: {"reject_rate": 0.08, "slippage_bps": 11.5}}
    )

    status = _check_execution_health(manifest, fail_state)
    assert status.disqualifying_reasons
    assert status.penalties["reject_rate"] == approx(0.0)
    assert status.penalties["slippage_bps"] == approx(0.0)
    assert status.score_delta == approx(0.0)
    fail_joined = " ".join(status.log_messages)
    assert "guard=" in fail_joined
    assert "ratio=" in fail_joined
    assert "margin=-" in fail_joined


def test_execution_health_fill_latency_penalties_and_alias():
    manifest = load_day_manifest()
    manifest.router.priority = 0.0
    manifest.router.max_reject_rate = None
    manifest.router.max_slippage_bps = None
    manifest.router.max_fill_latency_ms = 120.0
    manifest.router.max_latency_ms = 150.0

    ctx = {"session": "LDN", "spread_band": "narrow", "rv_band": "mid"}
    signals = {manifest.id: {"score": 1.0}}

    warning_state = PortfolioState(
        execution_health={manifest.id: {"fill_latency_ms": 118.0}}
    )
    fail_state = PortfolioState(
        execution_health={manifest.id: {"fill_latency_ms": 132.5}}
    )

    warning_result = select_candidates(
        ctx, [manifest], portfolio=warning_state, strategy_signals=signals
    )[0]
    assert warning_result.eligible is True
    assert warning_result.score == approx(0.85)
    warning_joined = " ".join(warning_result.reasons)
    assert "fill_latency_ms" in warning_joined
    assert "margin=+" in warning_joined
    assert "score_delta=-0.15" in warning_joined

    fail_result = select_candidates(ctx, [manifest], portfolio=fail_state)[0]
    assert fail_result.eligible is False
    fail_joined = " ".join(fail_result.reasons)
    assert "fill_latency_ms" in fail_joined
    assert "margin=-" in fail_joined
    assert any("ratio=" in reason for reason in fail_result.reasons)

    # Alias: drop explicit fill latency guard and rely on max_latency_ms fallback.
    manifest.router.max_fill_latency_ms = None
    manifest.router.max_latency_ms = 130.0
    alias_state = PortfolioState(
        execution_health={manifest.id: {"fill_latency_ms": 140.0}}
    )
    alias_status = _check_execution_health(manifest, alias_state)
    assert alias_status.disqualifying_reasons
    assert any("margin=-" in reason for reason in alias_status.disqualifying_reasons)


def test_priority_boosts_score():
    manifest = load_day_manifest()
    manifest.router.priority = 0.4
    ctx = {"session": "LDN", "spread_band": "narrow", "rv_band": "mid"}
    signals = {manifest.id: {"score": 1.1}}
    res = select_candidates(ctx, [manifest], strategy_signals=signals)
    assert res[0].score == 1.5


def test_headroom_adjusts_scores_and_reasons():
    manifest = load_day_manifest()
    manifest.router.priority = 0.0
    manifest.router.category_cap_pct = 50.0
    manifest.router.max_gross_exposure_pct = 80.0
    manifest.router.category_budget_pct = 50.0

    ctx = {"session": "LDN", "spread_band": "narrow", "rv_band": "mid"}
    signals = {manifest.id: {"score": 1.0}}

    near_limits = PortfolioState(
        category_utilisation_pct={manifest.category: 47.0},
        category_caps_pct={manifest.category: 50.0},
        category_headroom_pct={manifest.category: 3.0},
        gross_exposure_pct=76.0,
        gross_exposure_cap_pct=80.0,
        gross_exposure_headroom_pct=4.0,
    )

    ample_capacity = PortfolioState(
        category_utilisation_pct={manifest.category: 20.0},
        category_caps_pct={manifest.category: 50.0},
        category_headroom_pct={manifest.category: 30.0},
        gross_exposure_pct=35.0,
        gross_exposure_cap_pct=80.0,
        gross_exposure_headroom_pct=45.0,
    )

    near_result = select_candidates(
        ctx, [manifest], portfolio=near_limits, strategy_signals=signals
    )[0]
    ample_result = select_candidates(
        ctx, [manifest], portfolio=ample_capacity, strategy_signals=signals
    )[0]

    assert near_result.eligible is True
    assert ample_result.eligible is True
    assert near_result.score == approx(-0.05, abs=1e-6)
    assert ample_result.score == 1.3  # 1.0 +0.1 (category) +0.2 (gross)

    near_reasons = " ".join(near_result.reasons)
    ample_reasons = " ".join(ample_result.reasons)
    assert "category headroom" in near_reasons
    assert "gross headroom" in near_reasons
    assert "category budget headroom" in near_reasons
    assert "category budget headroom" in ample_reasons
    assert "score_delta=-0.50" in near_reasons
    assert "status=warning" in near_reasons
    assert "score_delta=-0.05" in near_reasons
    assert "score_delta=+0.20" in ample_reasons
    assert "status=ok" in ample_reasons


def test_budget_penalty_adjusts_scores_and_reasons():
    manifest = load_day_manifest()
    manifest.router.priority = 0.0
    manifest.router.category_cap_pct = 50.0
    manifest.router.category_budget_pct = 30.0

    ctx = {"session": "LDN", "spread_band": "narrow", "rv_band": "mid"}
    signals = {manifest.id: {"score": 1.0}}

    moderate_over = PortfolioState(
        category_utilisation_pct={manifest.category: 36.0},
        category_caps_pct={manifest.category: 50.0},
        category_headroom_pct={manifest.category: 14.0},
        category_budget_pct={manifest.category: 30.0},
        category_budget_headroom_pct={manifest.category: -6.0},
    )

    near_cap = PortfolioState(
        category_utilisation_pct={manifest.category: 48.0},
        category_caps_pct={manifest.category: 50.0},
        category_headroom_pct={manifest.category: 2.0},
        category_budget_pct={manifest.category: 30.0},
        category_budget_headroom_pct={manifest.category: -18.0},
    )

    moderate_result = select_candidates(
        ctx, [manifest], portfolio=moderate_over, strategy_signals=signals
    )[0]
    near_cap_result = select_candidates(
        ctx, [manifest], portfolio=near_cap, strategy_signals=signals
    )[0]

    assert moderate_result.score == approx(0.48)
    assert near_cap_result.score == approx(-0.30)

    moderate_reasons = " ".join(moderate_result.reasons)
    near_cap_reasons = " ".join(near_cap_result.reasons)
    assert "category budget headroom" in moderate_reasons
    assert "score_delta=-0.52" in moderate_reasons
    assert "status=breach" in moderate_reasons
    assert "category budget headroom" in near_cap_reasons
    assert "score_delta=-0.80" in near_cap_reasons
    assert "status=breach" in near_cap_reasons
