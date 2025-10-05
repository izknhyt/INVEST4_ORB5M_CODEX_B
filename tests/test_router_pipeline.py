import json
from pathlib import Path

from pytest import approx

from core.router_pipeline import (
    PortfolioTelemetry,
    build_correlation_maps,
    build_portfolio_state,
)
from configs.strategies.loader import load_manifest
from router.router_v1 import select_candidates


def test_router_pipeline_merges_limits_and_execution_health():
    day_manifest = load_manifest("configs/strategies/day_orb_5m.yaml")
    mean_manifest = load_manifest("configs/strategies/mean_reversion.yaml")

    # Ensure router guards are active for the test scenario.
    day_manifest.router.category_cap_pct = 40.0
    day_manifest.router.category_budget_pct = 35.0
    day_manifest.router.max_fill_latency_ms = 200.0
    day_manifest.router.max_latency_ms = 200.0
    mean_manifest.router.category_cap_pct = 40.0
    mean_manifest.router.max_reject_rate = 0.05
    mean_manifest.router.max_correlation = 0.6
    day_manifest.risk.max_concurrent_positions = 3
    mean_manifest.risk.max_concurrent_positions = 3

    telemetry = PortfolioTelemetry(
        active_positions={day_manifest.id: 1},
        category_utilisation_pct={"day": 39.5},
        category_caps_pct={"day": 42.0},
        category_budget_pct={"day": 33.0},
        gross_exposure_cap_pct=60.0,
        strategy_correlations={
            mean_manifest.id: {day_manifest.id: 0.4},
        },
    )
    runtime_metrics = {
        day_manifest.id: {
            "execution_health": {
                "reject_rate": 0.01,
                "slippage_bps": 3.0,
                "fill_latency_ms": 95.0,
            }
        },
        mean_manifest.id: {"execution_health": {"reject_rate": 0.09, "slippage_bps": 6.0}},
    }

    portfolio = build_portfolio_state(
        [day_manifest, mean_manifest], telemetry=telemetry, runtime_metrics=runtime_metrics
    )

    # Telemetry + manifest metadata combine to produce utilisation and caps.
    assert portfolio.category_utilisation_pct["day"] > 39.5
    assert portfolio.category_caps_pct["day"] == 40.0
    assert portfolio.category_headroom_pct["day"] == approx(
        portfolio.category_caps_pct["day"] - portfolio.category_utilisation_pct["day"]
    )
    assert portfolio.category_budget_pct["day"] == 33.0
    assert portfolio.category_budget_headroom_pct["day"] == approx(
        portfolio.category_budget_pct["day"]
        - portfolio.category_utilisation_pct["day"]
    )
    assert portfolio.category_budget_pct[mean_manifest.category] == portfolio.category_budget_pct[day_manifest.category]
    assert portfolio.active_positions[day_manifest.id] == 1
    assert portfolio.gross_exposure_pct == day_manifest.risk.risk_per_trade_pct
    assert portfolio.gross_exposure_cap_pct == 60.0
    assert portfolio.gross_exposure_headroom_pct == approx(
        portfolio.gross_exposure_cap_pct - portfolio.gross_exposure_pct
    )

    # Execution health is merged from BacktestRunner runtime metrics.
    assert portfolio.execution_health[day_manifest.id]["reject_rate"] == 0.01
    assert portfolio.execution_health[mean_manifest.id]["reject_rate"] == 0.09
    assert portfolio.execution_health[day_manifest.id]["fill_latency_ms"] == 95.0

    market_ctx = {"session": "LDN", "spread_band": "narrow", "rv_band": "mid"}
    results = select_candidates(market_ctx, [day_manifest, mean_manifest], portfolio=portfolio)
    result_map = {res.manifest_id: res for res in results}

    assert result_map[day_manifest.id].eligible is True
    assert result_map[mean_manifest.id].eligible is False
    assert any("reject_rate" in reason for reason in result_map[mean_manifest.id].reasons)


def test_router_pipeline_preserves_correlation_window_metadata():
    manifest = load_manifest("configs/strategies/day_orb_5m.yaml")
    telemetry = PortfolioTelemetry(
        strategy_correlations={manifest.id: {}},
        correlation_window_minutes=180.0,
    )

    portfolio = build_portfolio_state([manifest], telemetry=telemetry)

    assert portfolio.correlation_window_minutes == approx(180.0)


def test_router_pipeline_populates_correlation_metadata():
    day_manifest = load_manifest("configs/strategies/day_orb_5m.yaml")
    mean_manifest = load_manifest("configs/strategies/mean_reversion.yaml")
    day_manifest.router.category_budget_pct = 35.0
    mean_manifest.router.category_budget_pct = 35.0

    telemetry = PortfolioTelemetry(
        strategy_correlations={
            day_manifest.id: {mean_manifest.id: 0.55},
            "momentum": {mean_manifest.id: 0.6},
        }
    )

    portfolio = build_portfolio_state([day_manifest, mean_manifest], telemetry=telemetry)

    meta = portfolio.correlation_meta
    assert day_manifest.id in meta
    assert "momentum" in meta
    direct_meta = meta[day_manifest.id][mean_manifest.id]
    assert direct_meta["strategy_id"] == mean_manifest.id
    assert direct_meta["category"] == mean_manifest.category
    assert direct_meta["category_budget_pct"] == approx(35.0)
    assert direct_meta["bucket_category"] == mean_manifest.category
    assert direct_meta["bucket_budget_pct"] == approx(35.0)
    tag_meta = meta["momentum"][mean_manifest.id]
    assert tag_meta["strategy_id"] == mean_manifest.id
    assert tag_meta["category"] == mean_manifest.category
    assert tag_meta["category_budget_pct"] == approx(35.0)
    assert tag_meta["bucket_category"] == mean_manifest.category
    assert tag_meta["bucket_budget_pct"] == approx(35.0)


def test_build_correlation_maps_matches_portfolio_output():
    day_manifest = load_manifest("configs/strategies/day_orb_5m.yaml")
    mean_manifest = load_manifest("configs/strategies/mean_reversion.yaml")
    day_manifest.router.category_budget_pct = 35.0
    mean_manifest.router.category_budget_pct = 35.0

    telemetry = PortfolioTelemetry(
        strategy_correlations={
            day_manifest.id: {mean_manifest.id: "0.55"},
            "momentum": {mean_manifest.id: 0.6},
        },
        correlation_meta={
            "momentum": {
                mean_manifest.id: {
                    "bucket_category": "swing",
                    "bucket_budget_pct": 45.0,
                }
            }
        },
        category_budget_pct={day_manifest.category: 33.0},
    )

    manifest_index = {m.id: m for m in [day_manifest, mean_manifest]}
    category_budget_map = {day_manifest.category: 33.0}

    correlations, meta = build_correlation_maps(
        telemetry, manifest_index, category_budget_map
    )

    portfolio = build_portfolio_state(
        [day_manifest, mean_manifest], telemetry=telemetry
    )

    assert correlations == portfolio.strategy_correlations
    assert meta == portfolio.correlation_meta


def test_router_pipeline_preserves_bucket_metadata_without_peer_manifest():
    manifest = load_manifest("configs/strategies/day_orb_5m.yaml")
    telemetry = PortfolioTelemetry(
        strategy_correlations={manifest.id: {"external_peer": 0.7}},
        correlation_meta={
            manifest.id: {
                "external_peer": {
                    "bucket_category": "swing",
                    "bucket_budget_pct": 45.0,
                }
            }
        },
    )

    portfolio = build_portfolio_state([manifest], telemetry=telemetry)

    meta = portfolio.correlation_meta[manifest.id]["external_peer"]
    assert meta["bucket_category"] == "swing"
    assert meta["bucket_budget_pct"] == approx(45.0)
    assert meta["category"] == "swing"
    assert meta["category_budget_pct"] == approx(45.0)


def test_router_pipeline_skips_invalid_telemetry_values():
    day_manifest = load_manifest("configs/strategies/day_orb_5m.yaml")
    day_manifest.router.category_cap_pct = 50.0
    day_manifest.router.category_budget_pct = 45.0

    telemetry = PortfolioTelemetry(
        active_positions={day_manifest.id: 1},
        category_utilisation_pct={day_manifest.category: ""},
        category_caps_pct={day_manifest.category: "not-a-number"},
        category_budget_pct={day_manifest.category: "invalid"},
    )
    runtime_metrics = {
        day_manifest.id: {
            "execution_health": {
                "reject_rate": None,
                "slippage_bps": "5.5",
                "fill_latency_ms": "not-a-number",
            }
        }
    }

    portfolio = build_portfolio_state(
        [day_manifest], telemetry=telemetry, runtime_metrics=runtime_metrics
    )

    # Invalid telemetry should be ignored while manifest-derived data remains intact.
    assert day_manifest.category in portfolio.category_utilisation_pct
    assert portfolio.category_caps_pct[day_manifest.category] == day_manifest.router.category_cap_pct
    assert portfolio.category_headroom_pct[day_manifest.category] == approx(
        portfolio.category_caps_pct[day_manifest.category]
        - portfolio.category_utilisation_pct[day_manifest.category]
    )
    assert portfolio.category_budget_pct[day_manifest.category] == day_manifest.router.category_budget_pct
    assert portfolio.category_budget_headroom_pct[day_manifest.category] == approx(
        portfolio.category_budget_pct[day_manifest.category]
        - portfolio.category_utilisation_pct[day_manifest.category]
    )
    assert portfolio.execution_health[day_manifest.id]["slippage_bps"] == 5.5
    assert "reject_rate" not in portfolio.execution_health[day_manifest.id]
    assert "fill_latency_ms" not in portfolio.execution_health[day_manifest.id]


def test_router_pipeline_respects_budget_headroom_from_telemetry():
    manifest = load_manifest("configs/strategies/day_orb_5m.yaml")
    manifest.router.category_cap_pct = 55.0
    manifest.router.category_budget_pct = 50.0

    telemetry = PortfolioTelemetry(
        category_utilisation_pct={manifest.category: 25.0},
        category_budget_pct={manifest.category: 45.0},
        category_budget_headroom_pct={manifest.category: 20.0},
    )

    portfolio = build_portfolio_state([manifest], telemetry=telemetry)

    # Telemetry-provided headroom should be preserved rather than recomputed.
    assert portfolio.category_budget_pct[manifest.category] == 45.0
    assert portfolio.category_budget_headroom_pct[manifest.category] == approx(20.0)


def test_router_pipeline_recomputes_budget_headroom_on_tightened_budget():
    manifest = load_manifest("configs/strategies/day_orb_5m.yaml")
    manifest.router.category_cap_pct = 90.0
    manifest.router.category_budget_pct = 40.0

    telemetry = PortfolioTelemetry(
        category_utilisation_pct={manifest.category: 45.0},
        category_budget_pct={manifest.category: 60.0},
        category_budget_headroom_pct={manifest.category: 15.0},
    )

    portfolio = build_portfolio_state([manifest], telemetry=telemetry)

    assert portfolio.category_budget_pct[manifest.category] == approx(40.0)
    assert portfolio.category_budget_headroom_pct[manifest.category] == approx(-5.0)

    market_ctx = {"session": "LDN", "spread_band": "narrow", "rv_band": "mid"}
    result = select_candidates(market_ctx, [manifest], portfolio=portfolio)[0]

    assert any("status=breach" in reason for reason in result.reasons)
    expected_penalty = -0.25 - min(abs(-5.0) / 10.0, 1.0) * 0.45
    expected_headroom_delta = 0.2  # cap headroom is comfortably above thresholds.
    assert result.score == approx(
        manifest.router.priority + expected_headroom_delta + expected_penalty
    )


def test_router_pipeline_handles_none_reject_rate_and_blank_usage():
    manifest = load_manifest("configs/strategies/day_orb_5m.yaml")
    manifest.router.category_cap_pct = 55.0
    manifest.router.category_budget_pct = 55.0

    telemetry = PortfolioTelemetry(
        active_positions={manifest.id: 1},
        category_utilisation_pct={manifest.category: ""},
        gross_exposure_pct="",
    )
    runtime_metrics = {
        manifest.id: {"execution_health": {"reject_rate": None}}
    }

    portfolio = build_portfolio_state(
        [manifest], telemetry=telemetry, runtime_metrics=runtime_metrics
    )

    expected_exposure = float(manifest.risk.risk_per_trade_pct)
    assert portfolio.category_utilisation_pct[manifest.category] == approx(expected_exposure)
    assert portfolio.gross_exposure_pct == approx(expected_exposure)
    assert portfolio.gross_exposure_headroom_pct is None
    assert portfolio.category_budget_pct[manifest.category] == manifest.router.category_budget_pct
    assert portfolio.category_budget_headroom_pct[manifest.category] == approx(
        portfolio.category_budget_pct[manifest.category] - expected_exposure
    )
    assert "reject_rate" not in portfolio.execution_health.get(manifest.id, {})


def test_router_pipeline_preserves_budget_headroom_within_tolerance():
    manifest = load_manifest("configs/strategies/day_orb_5m.yaml")
    manifest.router.category_cap_pct = 55.0
    manifest.router.category_budget_pct = 50.0

    utilisation = 20.0
    telemetry_headroom = 50.0 - utilisation + 5e-10

    telemetry = PortfolioTelemetry(
        category_utilisation_pct={manifest.category: utilisation},
        category_budget_pct={manifest.category: 50.0},
        category_budget_headroom_pct={manifest.category: telemetry_headroom},
    )

    portfolio = build_portfolio_state([manifest], telemetry=telemetry)

    assert portfolio.category_budget_pct[manifest.category] == approx(50.0)
    assert portfolio.category_budget_headroom_pct[manifest.category] == approx(
        telemetry_headroom
    )


def test_router_pipeline_counts_shorts_for_limits():
    manifest = load_manifest("configs/strategies/day_orb_5m.yaml")
    manifest.router.category_cap_pct = 0.4
    manifest.router.category_budget_pct = 0.3
    manifest.risk.max_concurrent_positions = 1

    telemetry = PortfolioTelemetry(
        active_positions={manifest.id: -2},
        category_utilisation_pct={},
    )

    portfolio = build_portfolio_state([manifest], telemetry=telemetry)

    # Utilisation and gross exposure should use the absolute position count.
    expected_exposure = 2 * float(manifest.risk.risk_per_trade_pct)
    assert portfolio.category_utilisation_pct[manifest.category] == approx(
        expected_exposure
    )
    assert portfolio.gross_exposure_pct == approx(expected_exposure)
    assert portfolio.category_headroom_pct[manifest.category] == approx(
        manifest.router.category_cap_pct - expected_exposure
    )
    assert portfolio.category_budget_pct[manifest.category] == manifest.router.category_budget_pct
    assert portfolio.category_budget_headroom_pct[manifest.category] == approx(
        manifest.router.category_budget_pct - expected_exposure
    )
    assert portfolio.active_positions[manifest.id] == -2

    market_ctx = {"session": "LDN", "spread_band": "narrow", "rv_band": "mid"}
    result = select_candidates(market_ctx, [manifest], portfolio=portfolio)[0]

    assert result.eligible is False
    assert any("category utilisation" in reason for reason in result.reasons)
    assert any("active positions" in reason for reason in result.reasons)


def test_router_pipeline_merges_short_usage_with_existing_category_allocation():
    manifest = load_manifest("configs/strategies/day_orb_5m.yaml")
    manifest.router.category_cap_pct = 0.25
    manifest.router.category_budget_pct = 0.2
    manifest.risk.max_concurrent_positions = 1

    telemetry = PortfolioTelemetry(
        active_positions={manifest.id: -1},
        category_utilisation_pct={manifest.category: 0.1},
    )

    portfolio = build_portfolio_state([manifest], telemetry=telemetry)

    expected_usage = 0.1 + float(manifest.risk.risk_per_trade_pct)
    assert portfolio.category_utilisation_pct[manifest.category] == approx(expected_usage)
    assert portfolio.gross_exposure_pct == approx(float(manifest.risk.risk_per_trade_pct))
    assert portfolio.category_headroom_pct[manifest.category] == approx(
        manifest.router.category_cap_pct - expected_usage
    )
    assert portfolio.category_budget_pct[manifest.category] == manifest.router.category_budget_pct
    assert portfolio.category_budget_headroom_pct[manifest.category] == approx(
        manifest.router.category_budget_pct - expected_usage
    )

    market_ctx = {"session": "LDN", "spread_band": "narrow", "rv_band": "mid"}
    result = select_candidates(market_ctx, [manifest], portfolio=portfolio)[0]

    assert result.eligible is False
    assert any("category utilisation" in reason for reason in result.reasons)
    assert any("active positions" in reason for reason in result.reasons)


def test_router_pipeline_uses_governance_budget_when_router_missing():
    manifest = load_manifest("configs/strategies/day_orb_5m.yaml")
    manifest.router.category_cap_pct = 55.0
    manifest.router.category_budget_pct = None
    manifest.raw.setdefault("governance", {})["category_budget_pct"] = 44.0

    telemetry = PortfolioTelemetry(
        category_utilisation_pct={manifest.category: 12.5},
    )

    portfolio = build_portfolio_state([manifest], telemetry=telemetry)

    assert portfolio.category_budget_pct[manifest.category] == approx(44.0)
    assert portfolio.category_budget_headroom_pct[manifest.category] == approx(
        44.0 - 12.5
    )


def test_router_sample_metrics_equity_curve_is_ordered() -> None:
    metrics_dir = Path("reports/portfolio_samples/router_demo/metrics")
    assert metrics_dir.exists()
    for metrics_path in sorted(metrics_dir.glob("*.json")):
        payload = json.loads(metrics_path.read_text(encoding="utf-8"))
        curve = payload.get("equity_curve")
        assert isinstance(curve, list) and curve
        timestamps = []
        equities = []
        for entry in curve:
            assert isinstance(entry, list) and len(entry) >= 2
            ts, equity = entry[0], entry[1]
            assert isinstance(ts, str)
            timestamps.append(ts)
            equities.append(float(equity))
        assert timestamps == sorted(timestamps)
