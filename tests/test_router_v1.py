from configs.strategies.loader import load_manifest
from router.router_v1 import PortfolioState, select_candidates


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


def test_correlation_guard():
    manifest = load_day_manifest()
    manifest.router.max_correlation = 0.6
    portfolio = PortfolioState(
        strategy_correlations={manifest.id: {"active_day": 0.85}}
    )
    ctx = {"session": "LDN", "spread_band": "narrow", "rv_band": "mid"}
    res = select_candidates(ctx, [manifest], portfolio=portfolio)
    assert res[0].eligible is False
    assert any("correlation" in reason for reason in res[0].reasons)


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
    assert near_result.score == 0.0  # 1.0 -0.5 (category) -0.5 (gross)
    assert ample_result.score == 1.3  # 1.0 +0.1 (category) +0.2 (gross)

    near_reasons = " ".join(near_result.reasons)
    ample_reasons = " ".join(ample_result.reasons)
    assert "category headroom" in near_reasons
    assert "gross headroom" in near_reasons
    assert "score_delta=-0.50" in near_reasons
    assert "score_delta=+0.20" in ample_reasons
