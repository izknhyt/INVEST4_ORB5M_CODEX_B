from pathlib import Path

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
