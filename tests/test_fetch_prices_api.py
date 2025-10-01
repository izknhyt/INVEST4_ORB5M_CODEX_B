import json
import threading
import urllib.parse
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from core.utils import yaml_compat

from scripts.fetch_prices_api import fetch_prices
from scripts.pull_prices import ingest_records


class _MockHandler(BaseHTTPRequestHandler):
    queue = []
    paths = []

    def do_GET(self):  # pragma: no cover - exercised via tests
        spec = self.queue.pop(0) if self.queue else {"status": 200, "body": {"data": []}}
        status = spec.get("status", 200)
        body = spec.get("body", {})
        headers = spec.get("headers", {"Content-Type": "application/json"})
        _MockHandler.paths.append(self.path)
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.end_headers()
        if isinstance(body, (bytes, bytearray)):
            payload = body
        elif isinstance(body, str):
            payload = body.encode("utf-8")
        else:
            payload = json.dumps(body).encode("utf-8")
        self.wfile.write(payload)

    def log_message(self, *args, **kwargs):  # pragma: no cover - silence stdio
        return


@pytest.fixture
def api_server():
    _MockHandler.queue = []
    _MockHandler.paths = []
    server = HTTPServer(("127.0.0.1", 0), _MockHandler)
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}/bars"
    try:
        yield _MockHandler, base_url
    finally:
        server.shutdown()
        thread.join()


def _write_config(tmp_path: Path, base_url: str) -> tuple[Path, Path]:
    config_path = tmp_path / "config.yml"
    credentials_path = tmp_path / "keys.yml"
    config = {
        "default_provider": "mock",
        "lookback_minutes": 30,
        "providers": {
            "mock": {
                "base_url": base_url,
                "method": "GET",
                "query": {
                    "symbol": "{symbol}",
                    "tf": "{tf}",
                    "start": "{start_iso}",
                    "end": "{end_iso}",
                    "api_key": "{api_key}",
                },
                "credentials": ["api_key"],
                "lookback_minutes": 15,
                "response": {
                    "format": "json",
                    "data_path": ["data"],
                    "entry_type": "sequence",
                    "timestamp_field": "ts",
                    "fields": {
                        "o": "open",
                        "h": "high",
                        "l": "low",
                        "c": "close",
                        "v": "volume",
                        "spread": None,
                    },
                    "timestamp_formats": ["%Y-%m-%dT%H:%M:%S"],
                },
                "retry": {
                    "attempts": 2,
                    "backoff_seconds": 0.0,
                    "multiplier": 1.0,
                    "retryable_statuses": [500],
                },
                "rate_limit": {
                    "cooldown_seconds": 0.0,
                },
            }
        },
    }
    config_path.write_text(yaml_compat.safe_dump(config), encoding="utf-8")
    credentials_path.write_text(yaml_compat.safe_dump({"mock": {"api_key": "token"}}), encoding="utf-8")
    return config_path, credentials_path


def test_fetch_prices_success(tmp_path, api_server):
    handler, base_url = api_server
    config_path, credentials_path = _write_config(tmp_path, base_url)

    handler.queue = [
        {
            "status": 200,
            "body": {
                "data": [
                    {
                        "ts": "2025-01-01T00:00:00",
                        "open": "150.0",
                        "high": "150.1",
                        "low": "149.9",
                        "close": "150.05",
                        "volume": "120",
                    },
                    {
                        "ts": "2025-01-01T00:05:00",
                        "open": "150.05",
                        "high": "150.15",
                        "low": "149.95",
                        "close": "150.10",
                        "volume": "118",
                    },
                ]
            },
        }
    ]

    start = datetime(2025, 1, 1, 0, 0)
    end = start + timedelta(minutes=10)
    rows = fetch_prices(
        "USDJPY",
        "5m",
        start=start,
        end=end,
        provider="mock",
        config_path=config_path,
        credentials_path=credentials_path,
        anomaly_log_path=tmp_path / "anomalies.jsonl",
    )

    assert len(rows) == 2
    assert rows[0]["timestamp"].endswith("00:00:00Z")
    assert rows[-1]["timestamp"].endswith("00:05:00Z")
    assert rows[0]["symbol"] == "USDJPY"
    assert rows[0]["v"] == 120.0
    assert rows[0]["spread"] == 0.0

    parsed = urllib.parse.urlparse(handler.paths[0])
    params = urllib.parse.parse_qs(parsed.query)
    assert params["api_key"] == ["token"]
    assert params["symbol"] == ["USDJPY"]

    snapshot_path = tmp_path / "snapshot.json"
    raw_path = tmp_path / "raw" / "USDJPY" / "5m.csv"
    validated_path = tmp_path / "validated" / "USDJPY" / "5m.csv"
    features_path = tmp_path / "features" / "USDJPY" / "5m.csv"
    result = ingest_records(
        rows,
        symbol="USDJPY",
        tf="5m",
        snapshot_path=snapshot_path,
        raw_path=raw_path,
        validated_path=validated_path,
        features_path=features_path,
        source_name="api",
    )
    assert result["rows_validated"] == 2
    assert (tmp_path / "anomalies.jsonl").exists() is False


def test_fetch_prices_allows_whitelisted_status(tmp_path, api_server):
    handler, base_url = api_server
    config_path, credentials_path = _write_config(tmp_path, base_url)

    config = yaml_compat.safe_load(config_path.read_text(encoding="utf-8"))
    provider = config["providers"]["mock"]
    provider["response"]["data_path"] = ["values"]
    provider["response"]["timestamp_field"] = "datetime"
    provider["response"]["fields"] = {
        "o": "open",
        "h": "high",
        "l": "low",
        "c": "close",
        "v": "volume",
        "spread": None,
    }
    provider.setdefault("retry", {})["error_keys"] = [
        {"key": "status", "allowed_values": ["ok", "OK"]}
    ]
    config_path.write_text(yaml_compat.safe_dump(config), encoding="utf-8")

    handler.queue = [
        {
            "status": 200,
            "body": {
                "status": "ok",
                "values": [
                    {
                        "datetime": "2025-01-02 00:05:00",
                        "open": "150.05",
                        "high": "150.15",
                        "low": "149.95",
                        "close": "150.10",
                        "volume": "118",
                    },
                    {
                        "datetime": "2025-01-02 00:00:00",
                        "open": "150.00",
                        "high": "150.08",
                        "low": "149.90",
                        "close": "150.02",
                        "volume": "120",
                    },
                ],
            },
        }
    ]

    start = datetime(2025, 1, 2, 0, 0)
    end = start + timedelta(minutes=5)
    anomaly_log = tmp_path / "whitelist_anomalies.jsonl"
    rows = fetch_prices(
        "USDJPY",
        "5m",
        start=start,
        end=end,
        provider="mock",
        config_path=config_path,
        credentials_path=credentials_path,
        anomaly_log_path=anomaly_log,
    )

    assert [row["timestamp"] for row in rows] == [
        "2025-01-02T00:00:00Z",
        "2025-01-02T00:05:00Z",
    ]
    assert rows[0]["v"] == 120.0
    assert not anomaly_log.exists()


def test_fetch_prices_rejects_disallowed_status(tmp_path, api_server):
    handler, base_url = api_server
    config_path, credentials_path = _write_config(tmp_path, base_url)

    config = yaml_compat.safe_load(config_path.read_text(encoding="utf-8"))
    provider = config["providers"]["mock"]
    provider.setdefault("retry", {})["error_keys"] = [
        {"key": "status", "allowed_values": ["ok"]}
    ]
    config_path.write_text(yaml_compat.safe_dump(config), encoding="utf-8")

    handler.queue = [
        {
            "status": 200,
            "body": {
                "status": "error",
                "message": "quota exceeded",
                "data": [],
            },
        },
        {
            "status": 200,
            "body": {
                "status": "error",
                "message": "still failing",
                "data": [],
            },
        },
    ]

    anomaly_log = tmp_path / "status_anomalies.jsonl"
    start = datetime(2025, 1, 2, 0, 0)
    end = start + timedelta(minutes=5)

    with pytest.raises(RuntimeError):
        fetch_prices(
            "USDJPY",
            "5m",
            start=start,
            end=end,
            provider="mock",
            config_path=config_path,
            credentials_path=credentials_path,
            anomaly_log_path=anomaly_log,
        )

    log_entries = [json.loads(line) for line in anomaly_log.read_text().splitlines()]
    assert log_entries[-1]["error"].startswith("api_error_value:status=")


def test_fetch_prices_retry_logs_failure(tmp_path, api_server):
    handler, base_url = api_server
    config_path, credentials_path = _write_config(tmp_path, base_url)

    handler.queue = [
        {"status": 500, "body": {"error": "temporary"}},
        {"status": 500, "body": {"error": "still failing"}},
    ]

    anomaly_log = tmp_path / "anomalies.jsonl"
    start = datetime(2025, 1, 1, 0, 0)
    end = start + timedelta(minutes=5)

    with pytest.raises(RuntimeError):
        fetch_prices(
            "USDJPY",
            "5m",
            start=start,
            end=end,
            provider="mock",
            config_path=config_path,
            credentials_path=credentials_path,
            anomaly_log_path=anomaly_log,
        )

    assert anomaly_log.exists()
    log_entries = [json.loads(line) for line in anomaly_log.read_text().splitlines()]
    assert log_entries[-1]["type"] == "api_request_failure"
    assert len(handler.paths) == 2


def test_fetch_prices_optional_field_defaults(tmp_path, api_server):
    handler, base_url = api_server
    config_path, credentials_path = _write_config(tmp_path, base_url)

    config = yaml_compat.safe_load(config_path.read_text(encoding="utf-8"))
    provider = config["providers"]["mock"]
    provider["response"]["fields"]["v"] = {
        "source": "volume",
        "required": False,
        "default": 0.0,
    }
    config_path.write_text(yaml_compat.safe_dump(config), encoding="utf-8")

    handler.queue = [
        {
            "status": 200,
            "body": {
                "data": [
                    {
                        "ts": "2025-01-01T00:00:00",
                        "open": "150.0",
                        "high": "150.1",
                        "low": "149.9",
                        "close": "150.05",
                    },
                    {
                        "ts": "2025-01-01T00:05:00",
                        "open": "150.05",
                        "high": "150.15",
                        "low": "149.95",
                        "close": "150.10",
                        "volume": "  ",
                    },
                ]
            },
        }
    ]

    start = datetime(2025, 1, 1, 0, 0)
    end = start + timedelta(minutes=5)
    rows = fetch_prices(
        "USDJPY",
        "5m",
        start=start,
        end=end,
        provider="mock",
        config_path=config_path,
        credentials_path=credentials_path,
        anomaly_log_path=tmp_path / "optional_volume.jsonl",
    )

    assert [row["v"] for row in rows] == [0.0, 0.0]


def test_fetch_prices_missing_required_field_raises(tmp_path, api_server):
    handler, base_url = api_server
    config_path, credentials_path = _write_config(tmp_path, base_url)

    handler.queue = [
        {
            "status": 200,
            "body": {
                "data": [
                    {
                        "ts": "2025-01-01T00:00:00",
                        "high": "150.1",
                        "low": "149.9",
                        "close": "150.05",
                        "volume": "100",
                    }
                ]
            },
        }
    ]

    start = datetime(2025, 1, 1, 0, 0)
    end = start + timedelta(minutes=5)

    with pytest.raises(RuntimeError) as exc:
        fetch_prices(
            "USDJPY",
            "5m",
            start=start,
            end=end,
            provider="mock",
            config_path=config_path,
            credentials_path=credentials_path,
            anomaly_log_path=tmp_path / "missing_required.jsonl",
        )

    assert "missing_field:open" in str(exc.value)


def test_fetch_prices_invalid_value_raises(tmp_path, api_server):
    handler, base_url = api_server
    config_path, credentials_path = _write_config(tmp_path, base_url)

    handler.queue = [
        {
            "status": 200,
            "body": {
                "data": [
                    {
                        "ts": "2025-01-01T00:00:00",
                        "open": "150.0",
                        "high": "150.1",
                        "low": "149.9",
                        "close": "150.05",
                        "volume": "not_a_number",
                    }
                ]
            },
        }
    ]

    start = datetime(2025, 1, 1, 0, 0)
    end = start + timedelta(minutes=5)

    with pytest.raises(RuntimeError) as exc:
        fetch_prices(
            "USDJPY",
            "5m",
            start=start,
            end=end,
            provider="mock",
            config_path=config_path,
            credentials_path=credentials_path,
            anomaly_log_path=tmp_path / "invalid_value.jsonl",
        )

    assert "invalid_field_value:volume" in str(exc.value)
