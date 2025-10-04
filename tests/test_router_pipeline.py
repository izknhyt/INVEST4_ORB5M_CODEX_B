from core.router_pipeline import PortfolioTelemetry, build_portfolio_state
from configs.strategies.loader import load_manifest
from router.router_v1 import select_candidates


def test_router_pipeline_merges_limits_and_execution_health():
    day_manifest = load_manifest("configs/strategies/day_orb_5m.yaml")
    mean_manifest = load_manifest("configs/strategies/mean_reversion.yaml")

    # Ensure router guards are active for the test scenario.
    day_manifest.router.category_cap_pct = 40.0
    mean_manifest.router.category_cap_pct = 40.0
    mean_manifest.router.max_reject_rate = 0.05
    mean_manifest.router.max_correlation = 0.6
    day_manifest.risk.max_concurrent_positions = 3
    mean_manifest.risk.max_concurrent_positions = 3

    telemetry = PortfolioTelemetry(
        active_positions={day_manifest.id: 1},
        category_utilisation_pct={"day": 39.5},
        category_caps_pct={"day": 42.0},
        gross_exposure_cap_pct=60.0,
        strategy_correlations={
            mean_manifest.id: {day_manifest.id: 0.4},
        },
    )
    runtime_metrics = {
        day_manifest.id: {"execution_health": {"reject_rate": 0.01, "slippage_bps": 3.0}},
        mean_manifest.id: {"execution_health": {"reject_rate": 0.09, "slippage_bps": 6.0}},
    }

    portfolio = build_portfolio_state(
        [day_manifest, mean_manifest], telemetry=telemetry, runtime_metrics=runtime_metrics
    )

    # Telemetry + manifest metadata combine to produce utilisation and caps.
    assert portfolio.category_utilisation_pct["day"] > 39.5
    assert portfolio.category_caps_pct["day"] == 40.0
    assert portfolio.active_positions[day_manifest.id] == 1
    assert portfolio.gross_exposure_pct == day_manifest.risk.risk_per_trade_pct
    assert portfolio.gross_exposure_cap_pct == 60.0

    # Execution health is merged from BacktestRunner runtime metrics.
    assert portfolio.execution_health[day_manifest.id]["reject_rate"] == 0.01
    assert portfolio.execution_health[mean_manifest.id]["reject_rate"] == 0.09

    market_ctx = {"session": "LDN", "spread_band": "narrow", "rv_band": "mid"}
    results = select_candidates(market_ctx, [day_manifest, mean_manifest], portfolio=portfolio)
    result_map = {res.manifest_id: res for res in results}

    assert result_map[day_manifest.id].eligible is True
    assert result_map[mean_manifest.id].eligible is False
    assert any("reject_rate" in reason for reason in result_map[mean_manifest.id].reasons)
