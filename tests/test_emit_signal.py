import json
from unittest import mock

import notifications.emit_signal as emit


def test_resolve_webhook_urls_cli(monkeypatch):
    monkeypatch.delenv("SIGNAL_WEBHOOK_URLS", raising=False)
    urls = emit.resolve_webhook_urls("https://a, https://b")
    assert urls == ["https://a", "https://b"]


def test_resolve_webhook_urls_env(monkeypatch):
    monkeypatch.setenv("SIGNAL_WEBHOOK_URLS", "https://env1;https://env2")
    urls = emit.resolve_webhook_urls(None)
    assert urls == ["https://env1", "https://env2"]


def test_log_latency_and_fallback(tmp_path):
    latency = tmp_path / "latency.csv"
    fallback = tmp_path / "fallback.log"
    payload = emit.SignalPayload(
        signal_id="sig1",
        timestamp_utc="2025-09-21T12:00:00+00:00",
        side="BUY",
        entry=150.0,
        tp=151.0,
        sl=149.0,
        trail=0.0,
        confidence=0.5,
        meta={"note": "test"},
    )
    emit.log_latency(str(latency), payload.signal_id, payload.timestamp_utc, False, "error")
    emit.log_fallback(str(fallback), payload, "error")

    rows = latency.read_text().strip().splitlines()
    assert len(rows) == 2
    assert rows[1].startswith("sig1,")

    record = json.loads(fallback.read_text().strip())
    assert record["signal_id"] == "sig1"
    assert record["note"] == "error"


def test_log_files_without_dir(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    payload = emit.SignalPayload(
        signal_id="sig2",
        timestamp_utc="2025-09-21T12:05:00+00:00",
        side="SELL",
        entry=120.0,
        tp=119.5,
        sl=121.0,
        trail=0.0,
        confidence=0.6,
    )

    emit.log_latency("latency.csv", payload.signal_id, payload.timestamp_utc, True, "ok")
    emit.log_fallback("fallback.log", payload, "fallback")

    latency_path = tmp_path / "latency.csv"
    fallback_path = tmp_path / "fallback.log"
    assert latency_path.exists()
    assert fallback_path.exists()


def test_send_webhook_success(monkeypatch):
    class FakeResponse:
        status = 200
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(req, timeout=5.0):
        return FakeResponse()

    if emit.urllib is None:
        monkeypatch.setitem(emit.__dict__, "urllib", mock.Mock())
    monkeypatch.setattr(emit.urllib.request, "urlopen", fake_urlopen)

    payload = emit.SignalPayload(
        signal_id="sig1",
        timestamp_utc="2025-09-21T12:00:00+00:00",
        side="BUY",
        entry=150.0,
        tp=151.0,
        sl=149.0,
        trail=0.0,
        confidence=0.5,
    )
    ok, detail = emit.send_webhook("https://example.com", payload)
    assert ok is True
    assert detail == "status=200"
