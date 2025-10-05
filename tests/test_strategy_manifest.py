from pathlib import Path

from core.utils import yaml_compat as yaml

from configs.strategies.loader import CATEGORY_CHOICES, StrategyManifest, load_manifest, load_manifests


def test_load_single_manifest():
    manifest_path = Path("configs/strategies/day_orb_5m.yaml")
    manifest = load_manifest(manifest_path)
    assert isinstance(manifest, StrategyManifest)
    assert manifest.id == "day_orb_5m_v1"
    assert manifest.category in CATEGORY_CHOICES
    assert manifest.module == "strategies.day_orb_5m"
    assert manifest.class_name == "DayORB5m"
    assert manifest.strategy.instruments[0].symbol == "USDJPY"
    assert "atr14" in manifest.features.required
    assert "LDN" in manifest.router.allowed_sessions
    assert manifest.risk.risk_per_trade_pct > 0
    manifest_dict = manifest.to_dict()
    router_dict = manifest_dict["router"]
    assert router_dict["priority"] == 0.0
    assert router_dict["max_gross_exposure_pct"] is None
    assert router_dict["max_correlation"] is None
    assert router_dict["correlation_tags"] == []
    assert router_dict["max_reject_rate"] is None
    assert router_dict["max_slippage_bps"] is None
    assert router_dict["category_budget_pct"] == manifest.router.category_budget_pct


def test_load_all_manifests(tmp_path):
    # copy manifest to temp dir to ensure loader handles directories recursively
    src = Path("configs/strategies/day_orb_5m.yaml")
    dst_dir = tmp_path / "strategies"
    dst_dir.mkdir()
    dst = dst_dir / src.name
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    manifests = load_manifests(dst_dir)
    assert "day_orb_5m_v1" in manifests
    assert manifests["day_orb_5m_v1"].strategy.instruments[0].timeframe == "5m"


def test_router_round_trip_with_priority_and_limits(tmp_path):
    manifest_path = Path("configs/strategies/day_template.yaml")
    manifest = load_manifest(manifest_path)

    manifest_dict = manifest.to_dict()
    router_dict = manifest_dict["router"]
    assert router_dict["priority"] == manifest.router.priority
    assert router_dict["max_gross_exposure_pct"] == manifest.router.max_gross_exposure_pct
    assert router_dict["max_correlation"] == manifest.router.max_correlation
    assert router_dict["correlation_tags"] == list(manifest.router.correlation_tags)
    assert router_dict["max_reject_rate"] == manifest.router.max_reject_rate
    assert router_dict["max_slippage_bps"] == manifest.router.max_slippage_bps
    assert router_dict["category_budget_pct"] == manifest.router.category_budget_pct

    round_trip_manifest = {
        "meta": {
            "id": manifest_dict["id"],
            "name": manifest_dict["name"],
            "version": manifest_dict["version"],
            "category": manifest_dict["category"],
            "description": manifest_dict["description"],
            "tags": manifest_dict["tags"],
        },
        "strategy": manifest_dict["strategy"],
        "router": router_dict,
        "risk": manifest_dict["risk"],
        "features": manifest_dict["features"],
        "runner": manifest_dict["runner"],
        "state": manifest_dict["state"],
    }

    round_trip_path = tmp_path / "round_trip_day_template.yaml"
    round_trip_path.write_text(
        yaml.safe_dump(round_trip_manifest, sort_keys=False),
        encoding="utf-8",
    )

    reloaded = load_manifest(round_trip_path)
    assert reloaded.router.priority == manifest.router.priority
    assert reloaded.router.max_gross_exposure_pct == manifest.router.max_gross_exposure_pct
    assert reloaded.router.max_correlation == manifest.router.max_correlation
    assert reloaded.router.correlation_tags == manifest.router.correlation_tags
    assert reloaded.router.max_reject_rate == manifest.router.max_reject_rate
    assert reloaded.router.max_slippage_bps == manifest.router.max_slippage_bps
    assert reloaded.router.category_budget_pct == manifest.router.category_budget_pct
