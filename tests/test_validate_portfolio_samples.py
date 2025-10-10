from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from scripts import validate_portfolio_samples

ROUTER_SAMPLES = Path("reports/portfolio_samples/router_demo")


def test_validate_router_demo_samples_pass() -> None:
    result = validate_portfolio_samples.validate_samples(ROUTER_SAMPLES)
    assert set(result.metrics_paths) == {"day_orb_5m_v1", "tokyo_micro_mean_reversion_v0"}
    assert result.telemetry_path.exists()


def test_validate_router_demo_samples_detects_manifest_mismatch(tmp_path: Path) -> None:
    sample_copy = tmp_path / "router_demo"
    shutil.copytree(ROUTER_SAMPLES, sample_copy)

    metrics_path = sample_copy / "metrics" / "day_orb_5m_v1.json"
    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    payload["manifest_path"] = "configs/strategies/tokyo_micro_mean_reversion.yaml"
    metrics_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(validate_portfolio_samples.SampleValidationError) as excinfo:
        validate_portfolio_samples.validate_samples(sample_copy)
    assert "manifest id mismatch" in str(excinfo.value)


def test_validate_router_demo_samples_detects_unknown_telemetry_id(tmp_path: Path) -> None:
    sample_copy = tmp_path / "router_demo"
    shutil.copytree(ROUTER_SAMPLES, sample_copy)

    telemetry_path = sample_copy / "telemetry.json"
    telemetry_payload = json.loads(telemetry_path.read_text(encoding="utf-8"))
    telemetry_payload.setdefault("active_positions", {})["ghost_strategy"] = 1
    telemetry_path.write_text(json.dumps(telemetry_payload, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(validate_portfolio_samples.SampleValidationError) as excinfo:
        validate_portfolio_samples.validate_samples(sample_copy)
    assert "ghost_strategy" in str(excinfo.value)
