from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

import pytest

from scripts import compare_metrics as compare_module
from scripts._webhook import WebhookDeliveryResult


def run_cli(tmp_path: Path, args: list[str]) -> subprocess.CompletedProcess:
    cmd = [
        sys.executable,
        str(Path(compare_module.__file__).resolve()),
        *args,
    ]
    return subprocess.run(cmd, check=True, capture_output=True, text=True, cwd=tmp_path)


def test_compare_metrics_reports_no_differences(tmp_path: Path):
    left = {"trades": 10, "wins": 5, "debug": {"ev_bypass": 0}}
    result = compare_module.compare_metrics(
        left,
        left,
        left_path=Path("left.json"),
        right_path=Path("right.json"),
    )

    assert not result.differences
    assert not result.missing_in_left
    assert not result.missing_in_right
    assert not result.significant_differences


def test_compare_metrics_detects_numeric_difference(tmp_path: Path):
    left = {"trades": 10, "wins": 5}
    right = {"trades": 11, "wins": 5}

    result = compare_module.compare_metrics(
        left,
        right,
        left_path=Path("left.json"),
        right_path=Path("right.json"),
        abs_tolerance=0.0,
        rel_tolerance=0.0,
    )

    assert result.significant_differences
    diff = result.significant_differences[0]
    assert diff.key == "trades"
    assert diff.abs_delta == pytest.approx(1.0)
    assert not diff.within_tolerance


def test_compare_metrics_honours_tolerance(tmp_path: Path):
    left = {"total_pips": 100.0}
    right = {"total_pips": 100.0004}

    result = compare_module.compare_metrics(
        left,
        right,
        left_path=Path("left.json"),
        right_path=Path("right.json"),
        abs_tolerance=0.001,
        rel_tolerance=0.0,
    )

    assert result.differences
    diff = result.differences[0]
    assert diff.within_tolerance
    assert not result.significant_differences


def test_compare_metrics_handles_missing_keys():
    left = {"trades": 10}
    right = {"wins": 5}

    result = compare_module.compare_metrics(
        left,
        right,
        left_path=Path("left.json"),
        right_path=Path("right.json"),
    )

    assert "trades" in result.missing_in_right
    assert "wins" in result.missing_in_left
    assert result.significant_differences == []


def test_cli_outputs_diff_and_exit_code(tmp_path: Path):
    left_path = tmp_path / "baseline.json"
    right_path = tmp_path / "candidate.json"
    left_path.write_text(json.dumps({"trades": 10, "state_loaded": "a"}), encoding="utf-8")
    right_path.write_text(json.dumps({"trades": 11, "state_loaded": "b"}), encoding="utf-8")

    args = [
        "--left",
        str(left_path),
        "--right",
        str(right_path),
        "--ignore",
        "state_loaded",
        "--abs-tol",
        "0.0",
    ]

    with pytest.raises(subprocess.CalledProcessError) as excinfo:
        run_cli(tmp_path, args)

    stderr = excinfo.value.stderr
    stdout = excinfo.value.stdout
    assert "Differences:" in stdout
    assert "trades" in stdout
    assert "Metrics comparison" not in stderr
    before_differences, _, after_differences = stdout.partition("Differences:")
    assert "state_loaded" in before_differences
    assert "state_loaded" not in after_differences


def test_dispatch_diff_webhooks_sends_payload(monkeypatch):
    result = compare_module.compare_metrics(
        {"trades": 10},
        {"trades": 11},
        left_path=Path("left.json"),
        right_path=Path("right.json"),
    )

    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_deliver(url: str, payload: Mapping[str, Any], **kwargs: Any) -> WebhookDeliveryResult:
        calls.append((url, payload))
        return WebhookDeliveryResult(url=url, status="ok", attempts=1, status_code=200, response_ms=10.5)

    monkeypatch.setattr(compare_module, "deliver_webhook", fake_deliver)

    config = compare_module.WebhookConfig(
        urls=("https://example.com/hook",),
        timeout=3.0,
        secret=None,
        dry_run=False,
        fail_on_error=False,
    )

    deliveries = compare_module.dispatch_diff_webhooks(result, config)

    assert len(calls) == 1
    assert calls[0][0] == "https://example.com/hook"
    payload = calls[0][1]
    assert payload["status"] == "diff_detected"
    assert payload["summary"]["significant_differences"] == 1
    assert deliveries == [
        {
            "url": "https://example.com/hook",
            "status": "ok",
            "attempts": 1,
            "status_code": 200,
            "response_ms": 10.5,
            "error": None,
        }
    ]


def test_dispatch_diff_webhooks_respects_dry_run(monkeypatch):
    result = compare_module.compare_metrics(
        {"trades": 10},
        {"trades": 11},
        left_path=Path("left.json"),
        right_path=Path("right.json"),
    )

    def fake_deliver(*_args: Any, **_kwargs: Any) -> WebhookDeliveryResult:
        raise AssertionError("deliver_webhook should not be called in dry-run mode")

    monkeypatch.setattr(compare_module, "deliver_webhook", fake_deliver)

    config = compare_module.WebhookConfig(
        urls=("https://example.com/hook",),
        timeout=5.0,
        secret="token",
        dry_run=True,
        fail_on_error=True,
    )

    deliveries = compare_module.dispatch_diff_webhooks(result, config)

    assert deliveries == [{"url": "https://example.com/hook", "status": "dry_run"}]


def test_resolve_webhook_config_collects_urls(monkeypatch):
    monkeypatch.setenv("COMPARE_WEBHOOKS", "https://example.com/one, https://example.com/two")
    monkeypatch.setenv("COMPARE_SECRET", "  secret-value  ")

    args = SimpleNamespace(
        webhook_url=["https://example.com/one", "https://example.com/three"],
        webhook_url_env="COMPARE_WEBHOOKS",
        webhook_timeout=7.5,
        webhook_secret_env="COMPARE_SECRET",
        dry_run_webhook=False,
        fail_on_webhook_error=True,
    )

    config = compare_module._resolve_webhook_config(args)
    assert config is not None
    assert config.urls == (
        "https://example.com/one",
        "https://example.com/three",
        "https://example.com/two",
    )
    assert config.timeout == pytest.approx(7.5)
    assert config.secret == "secret-value"
    assert config.fail_on_error is True


def test_resolve_webhook_config_rejects_invalid_timeout():
    args = SimpleNamespace(
        webhook_url=["https://example.com/hook"],
        webhook_url_env=None,
        webhook_timeout=0,
        webhook_secret_env=None,
        dry_run_webhook=False,
        fail_on_webhook_error=False,
    )

    with pytest.raises(ValueError):
        compare_module._resolve_webhook_config(args)
