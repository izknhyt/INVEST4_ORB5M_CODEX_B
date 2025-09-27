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


def test_scoring_sorting():
    manifest = load_day_manifest()
    ctx = {"session": "LDN", "spread_band": "narrow", "rv_band": "mid"}
    signals = {manifest.id: {"score": 1.5, "ev_lcb": 0.7}}
    res = select_candidates(ctx, [manifest], strategy_signals=signals)
    assert res[0].score == 1.5
    assert any("ev_lcb" in reason for reason in res[0].reasons)
