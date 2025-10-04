import json
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from core.utils import yaml_compat

import scripts.fetch_prices_api as fetch_prices_module
from scripts.fetch_prices_api import fetch_prices
from scripts.pull_prices import ingest_records


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


@pytest.fixture
def api_client(monkeypatch) -> SimpleNamespace:
    requests: list[dict[str, str]] = []
    response_queue: list[dict[str, object]] = []

    class _Response:
        def __init__(self, status: int, body: bytes, headers: dict[str, str], reason: str):
            self.status = status
            self._body = body
            self.headers = headers
            self.reason = reason

        def read(self) -> bytes:
            return self._body

        def __enter__(self) -> "_Response":
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:  # pragma: no cover - no special handling
            return False

    def enqueue(*, status: int = 200, body=None, headers: dict[str, str] | None = None, reason: str = "OK") -> None:
        if body is None:
            payload = b"{}"
        elif isinstance(body, (dict, list)):
            payload = json.dumps(body).encode("utf-8")
        elif isinstance(body, str):
            payload = body.encode("utf-8")
        elif isinstance(body, (bytes, bytearray)):
            payload = bytes(body)
        else:  # pragma: no cover - defensive
            raise TypeError(f"unsupported body type: {type(body)!r}")
        response_queue.append(
            {
                "status": int(status),
                "body": payload,
                "headers": headers or {},
                "reason": reason,
            }
        )

    def _urlopen(request, timeout=None):  # pragma: no cover - exercised indirectly by fetch_prices
        if isinstance(request, urllib.request.Request):
            url = request.full_url
        else:
            url = str(request)
        requests.append({"url": url})

        if not response_queue:
            raise AssertionError("no queued responses for urlopen")

        spec = response_queue.pop(0)
        return _Response(spec["status"], spec["body"], spec["headers"], spec["reason"])

    monkeypatch.setattr(fetch_prices_module.urllib.request, "urlopen", _urlopen)
    monkeypatch.setattr(fetch_prices_module, "_SLEEP", lambda *_: None)

    return SimpleNamespace(
        base_url="https://mock.api.test/bars",
        enqueue=enqueue,
        requests=requests,
    )


def test_fetch_prices_success(tmp_path: Path, api_client: SimpleNamespace):
    config_path, credentials_path = _write_config(tmp_path, api_client.base_url)

    api_client.enqueue(
        body={
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
        }
    )

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

    request_url = api_client.requests[0]["url"]
    parsed = urllib.parse.urlparse(request_url)
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


def test_fetch_prices_allows_whitelisted_status(tmp_path: Path, api_client: SimpleNamespace):
    config_path, credentials_path = _write_config(tmp_path, api_client.base_url)

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

    api_client.enqueue(
        body={
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
        }
    )

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


def test_fetch_prices_twelve_data_like_payload(tmp_path: Path, api_client: SimpleNamespace):
    config_path, credentials_path = _write_config(tmp_path, api_client.base_url)

    config = yaml_compat.safe_load(config_path.read_text(encoding="utf-8"))
    provider = config["providers"]["mock"]
    provider["query"]["symbol"] = "{base}/{quote}"
    provider["query"]["interval"] = "{interval}"
    provider["tf_map"] = {"5m": "5min"}
    provider["response"]["data_path"] = ["values"]
    provider["response"]["entry_type"] = "sequence"
    provider["response"]["timestamp_field"] = "datetime"
    provider["response"]["fields"]["v"] = {
        "source": "volume",
        "required": False,
        "default": 0.0,
    }
    provider["response"]["timestamp_formats"] = ["%Y-%m-%d %H:%M:%S"]
    provider.setdefault("retry", {})["error_keys"] = [
        {"key": "status", "allowed_values": ["ok"]}
    ]
    config_path.write_text(yaml_compat.safe_dump(config), encoding="utf-8")

    api_client.enqueue(
        body={
            "status": "ok",
            "meta": {
                "symbol": "USD/JPY",
                "interval": "5min",
                "timezone": "UTC",
            },
            "values": [
                {
                    "datetime": "2025-01-03 00:05:00+00:00",
                    "open": "150.05",
                    "high": "150.15",
                    "low": "149.95",
                    "close": "150.10",
                    "volume": "",
                },
                {
                    "datetime": "2025-01-03 00:00:00",
                    "open": "150.00",
                    "high": "150.08",
                    "low": "149.90",
                    "close": "150.02",
                    "volume": None,
                },
                {
                    "datetime": "2025-01-02 23:55:00",
                    "open": "149.95",
                    "high": "150.05",
                    "low": "149.85",
                    "close": "149.98",
                    "volume": "150",
                },
            ],
        }
    )

    start = datetime(2025, 1, 3, 0, 0)
    end = start + timedelta(minutes=5)
    anomaly_log = tmp_path / "twelve_data.jsonl"

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
        "2025-01-03T00:00:00Z",
        "2025-01-03T00:05:00Z",
    ]
    assert [row["v"] for row in rows] == [0.0, 0.0]
    assert [row["symbol"] for row in rows] == ["USDJPY", "USDJPY"]
    assert not anomaly_log.exists()

    request_url = api_client.requests[0]["url"]
    params = urllib.parse.parse_qs(urllib.parse.urlparse(request_url).query)
    assert params["symbol"] == ["USD/JPY"]
    assert params["interval"] == ["5min"]


def test_fetch_prices_rejects_disallowed_status(tmp_path: Path, api_client: SimpleNamespace):
    config_path, credentials_path = _write_config(tmp_path, api_client.base_url)

    config = yaml_compat.safe_load(config_path.read_text(encoding="utf-8"))
    provider = config["providers"]["mock"]
    provider.setdefault("retry", {})["error_keys"] = [
        {"key": "status", "allowed_values": ["ok"]}
    ]
    config_path.write_text(yaml_compat.safe_dump(config), encoding="utf-8")

    api_client.enqueue(
        body={
            "status": "error",
            "message": "quota exceeded",
            "data": [],
        }
    )
    api_client.enqueue(
        body={
            "status": "error",
            "message": "still failing",
            "data": [],
        }
    )

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


def test_fetch_prices_retry_logs_failure(tmp_path: Path, api_client: SimpleNamespace):
    config_path, credentials_path = _write_config(tmp_path, api_client.base_url)

    api_client.enqueue(status=500, body={"error": "temporary"})
    api_client.enqueue(status=500, body={"error": "still failing"})

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
    assert len(api_client.requests) == 2


def test_fetch_prices_optional_field_defaults(tmp_path: Path, api_client: SimpleNamespace):
    config_path, credentials_path = _write_config(tmp_path, api_client.base_url)

    config = yaml_compat.safe_load(config_path.read_text(encoding="utf-8"))
    provider = config["providers"]["mock"]
    provider["response"]["fields"]["v"] = {
        "source": "volume",
        "required": False,
        "default": 0.0,
    }
    config_path.write_text(yaml_compat.safe_dump(config), encoding="utf-8")

    api_client.enqueue(
        body={
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
        }
    )

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


def test_fetch_prices_missing_required_field_raises(tmp_path: Path, api_client: SimpleNamespace):
    config_path, credentials_path = _write_config(tmp_path, api_client.base_url)

    api_client.enqueue(
        body={
            "data": [
                {
                    "ts": "2025-01-01T00:00:00",
                    "high": "150.1",
                    "low": "149.9",
                    "close": "150.05",
                    "volume": "100",
                }
            ]
        }
    )

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


def test_fetch_prices_invalid_value_raises(tmp_path: Path, api_client: SimpleNamespace):
    config_path, credentials_path = _write_config(tmp_path, api_client.base_url)

    api_client.enqueue(
        body={
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
        }
    )

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
