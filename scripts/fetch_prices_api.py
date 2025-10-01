"""REST API fetcher for price ingestion."""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence

from core.utils import yaml_compat as yaml

from scripts._secrets import load_api_credentials
from scripts._ts_utils import parse_naive_utc_timestamp

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "configs/api_ingest.yml"
DEFAULT_CREDENTIALS_PATH = ROOT / "configs/api_keys.yml"
DEFAULT_ANOMALY_LOG = ROOT / "ops/logs/ingest_anomalies.jsonl"

_SLEEP = time.sleep

_MISSING = object()


def _as_list(value):
    """Return a list representation for config-provided value collections."""

    if value is None:
        return None
    if isinstance(value, (list, tuple, set, frozenset)):
        return list(value)
    return [value]


def _resolve_error_path(spec: Mapping[str, object]) -> Optional[List[object]]:
    """Return the lookup path for an error condition specification."""

    if "path" in spec:
        path_value = spec.get("path")
        if isinstance(path_value, str):
            return [part for part in path_value.split(".") if part]
        if isinstance(path_value, Sequence):
            return list(path_value)
    key_name = spec.get("key") or spec.get("name")
    if isinstance(key_name, str) and key_name:
        return [key_name]
    return None


def _lookup_value(payload: Mapping[str, object], path: Sequence[object]) -> object:
    current: object = payload
    for part in path:
        if isinstance(current, Mapping):
            current = current.get(part)
        elif isinstance(current, Sequence) and not isinstance(current, (str, bytes, bytearray)):
            index = part if isinstance(part, int) else int(part)
            current = current[index]
        else:
            return _MISSING
        if current is None:
            return None
    return current


def _evaluate_error_conditions(
    payload: Mapping[str, object],
    specs: Iterable[object],
) -> Optional[str]:
    """Return an error reason when config-defined conditions flag the payload."""

    for entry in specs or ():
        if isinstance(entry, str):
            if entry in payload:
                return f"api_error_key:{entry}"
            continue

        if not isinstance(entry, Mapping):
            continue

        path = _resolve_error_path(entry)
        if not path:
            continue

        value = _lookup_value(payload, path)
        allowed = _as_list(entry.get("allowed_values"))
        disallowed = _as_list(entry.get("disallowed_values"))
        trigger_on_missing = bool(entry.get("trigger_on_missing"))

        if value is _MISSING:
            if trigger_on_missing or allowed is not None:
                return f"api_error_missing:{'.'.join(str(p) for p in path)}"
            continue

        if allowed is not None:
            if value not in allowed:
                return (
                    "api_error_value:" +
                    f"{'.'.join(str(p) for p in path)}={value}"
                )
            continue

        if disallowed is not None:
            if value in disallowed:
                return (
                    "api_error_value:" +
                    f"{'.'.join(str(p) for p in path)}={value}"
                )
            continue

        if entry.get("equals") is not None:
            if value == entry.get("equals"):
                return (
                    "api_error_value:" +
                    f"{'.'.join(str(p) for p in path)}={value}"
                )
            continue

        if entry.get("not_equals") is not None:
            if value != entry.get("not_equals"):
                return (
                    "api_error_value:" +
                    f"{'.'.join(str(p) for p in path)}={value}"
                )
            continue

        # Default behaviour: flag presence of the key/path.
        joined = ".".join(str(p) for p in path)
        return f"api_error_key:{joined}"

    return None


@dataclass
class ProviderConfig:
    name: str
    data: Mapping[str, object]

    def get(self, key: str, default=None):
        return self.data.get(key, default)


def _load_config(path: Path | str) -> Dict[str, object]:
    cfg_path = Path(path)
    if not cfg_path.exists():
        raise RuntimeError(f"api_config_not_found:{cfg_path}")
    with cfg_path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise RuntimeError("invalid_api_config_format")
    return data


def _select_provider(config: Mapping[str, object], name: Optional[str]) -> ProviderConfig:
    providers = config.get("providers")
    if not isinstance(providers, Mapping):
        raise RuntimeError("api_provider_map_missing")
    provider_name = name or config.get("default_provider")
    if provider_name is None:
        provider_name = next(iter(providers.keys()))
    provider_data = providers.get(provider_name)
    if not isinstance(provider_data, Mapping):
        raise RuntimeError(f"unknown_api_provider:{provider_name}")
    return ProviderConfig(name=str(provider_name), data=provider_data)


def _symbol_parts(symbol: str) -> tuple[str, str]:
    sym = symbol.upper()
    if len(sym) >= 6:
        return sym[:3], sym[3:]
    return sym, ""


def _format_context(
    symbol: str,
    tf: str,
    *,
    start: datetime,
    end: datetime,
    provider: ProviderConfig,
    credentials: Mapping[str, str],
) -> Dict[str, str]:
    base, quote = _symbol_parts(symbol)
    tf_map = provider.get("tf_map", {})
    interval = tf_map.get(tf, tf) if isinstance(tf_map, Mapping) else tf
    context = {
        "symbol": symbol.upper(),
        "tf": tf,
        "interval": interval,
        "base": base,
        "quote": quote,
        "start_iso": start.replace(tzinfo=timezone.utc).isoformat(timespec="seconds"),
        "end_iso": end.replace(tzinfo=timezone.utc).isoformat(timespec="seconds"),
        "start_date": start.strftime("%Y-%m-%d"),
        "end_date": end.strftime("%Y-%m-%d"),
    }
    context.update(credentials)
    return context


def _format_mapping(data: Mapping[str, object], context: Mapping[str, str]) -> Dict[str, str]:
    formatted: Dict[str, str] = {}
    for key, value in data.items():
        if isinstance(value, str):
            formatted[key] = value.format(**context)
        else:
            formatted[key] = value
    return formatted


def _build_url(provider: ProviderConfig, context: Mapping[str, str]) -> tuple[str, Dict[str, str]]:
    base_url = provider.get("base_url")
    if not isinstance(base_url, str):
        raise RuntimeError("provider_base_url_missing")
    query = provider.get("query", {})
    if not isinstance(query, Mapping):
        raise RuntimeError("provider_query_missing")
    formatted_query = _format_mapping(query, context)
    headers = provider.get("headers", {})
    if not isinstance(headers, Mapping):
        raise RuntimeError("provider_headers_invalid")
    formatted_headers = _format_mapping(headers, context)
    method = str(provider.get("method", "GET")).upper()
    if method != "GET":
        raise RuntimeError("unsupported_provider_method")
    url = base_url
    if formatted_query:
        url = f"{base_url}?{urllib.parse.urlencode(formatted_query)}"
    return url, formatted_headers


def _append_anomaly(entry: Mapping[str, object], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _request_json(
    url: str,
    headers: Mapping[str, str],
    *,
    provider: ProviderConfig,
    anomaly_log_path: Path,
) -> Mapping[str, object]:
    retry_cfg = provider.get("retry", {})
    attempts = int(retry_cfg.get("attempts", 3))
    backoff = float(retry_cfg.get("backoff_seconds", 1.0))
    multiplier = float(retry_cfg.get("multiplier", 2.0))
    max_backoff = float(retry_cfg.get("max_backoff_seconds", backoff * 4))
    retryable_statuses = {int(code) for code in retry_cfg.get("retryable_statuses", [])}
    error_keys = retry_cfg.get("error_keys", [])
    timeout = float(provider.get("timeout_seconds", 30.0))

    rate_cfg = provider.get("rate_limit", {})
    cooldown = float(rate_cfg.get("cooldown_seconds", 0.0))
    last_request = None

    last_error: Optional[Exception] = None
    for attempt in range(1, attempts + 1):
        if cooldown > 0 and last_request is not None:
            elapsed = time.monotonic() - last_request
            delay = cooldown - elapsed
            if delay > 0:
                _SLEEP(delay)
        last_request = time.monotonic()

        request = urllib.request.Request(url, headers=dict(headers))
        try:
            with urllib.request.urlopen(request, timeout=timeout) as resp:
                if resp.status >= 400:
                    raise urllib.error.HTTPError(
                        url, resp.status, resp.reason, resp.headers, None
                    )
                body = resp.read().decode("utf-8")
                data = json.loads(body)
        except urllib.error.HTTPError as exc:
            if exc.code not in retryable_statuses or attempt == attempts:
                last_error = exc
                break
            last_error = exc
        except urllib.error.URLError as exc:
            if attempt == attempts:
                last_error = exc
                break
            last_error = exc
        except json.JSONDecodeError as exc:
            last_error = exc
            break
        else:
            error_reason = (
                _evaluate_error_conditions(data, error_keys)
                if isinstance(error_keys, Iterable)
                else None
            )
            if error_reason is None:
                return data

            last_error = RuntimeError(error_reason)
            if attempt == attempts:
                break

        sleep_for = min(backoff * (multiplier ** (attempt - 1)), max_backoff)
        _SLEEP(sleep_for)

    if last_error is None:
        last_error = RuntimeError("api_request_failed")

    _append_anomaly(
        {
            "type": "api_request_failure",
            "provider": provider.name,
            "url": url,
            "error": str(last_error),
        },
        anomaly_log_path,
    )
    raise RuntimeError("api_request_failure") from last_error


def _resolve_data_path(
    payload: Mapping[str, object],
    provider: ProviderConfig,
    context: Mapping[str, str],
) -> object:
    response_cfg = provider.get("response", {})
    if not isinstance(response_cfg, Mapping):
        raise RuntimeError("provider_response_missing")
    data_path = response_cfg.get("data_path", [])
    current: object = payload
    formatted_path: List[object] = []
    for item in data_path:
        if isinstance(item, str):
            formatted_path.append(item.format(**context))
        else:
            formatted_path.append(item)
    for key in formatted_path:
        if isinstance(current, Mapping):
            current = current.get(key)
        elif isinstance(current, Sequence) and not isinstance(current, (str, bytes)):
            index = key if isinstance(key, int) else int(key)
            current = current[index]
        else:
            raise RuntimeError("response_path_invalid")
    if current is None:
        raise RuntimeError("response_path_missing")
    return current


def _normalize_timestamp(value: str, *, formats: Sequence[str] | None) -> datetime:
    if formats:
        return parse_naive_utc_timestamp(value, fallback_formats=formats)
    return parse_naive_utc_timestamp(value)


def _normalize_rows(
    data: object,
    *,
    provider: ProviderConfig,
    context: Mapping[str, str],
    symbol: str,
    tf: str,
    start: datetime,
    end: datetime,
) -> List[Dict[str, object]]:
    response_cfg = provider.get("response", {})
    entry_type = response_cfg.get("entry_type", "mapping")
    timestamp_field = response_cfg.get("timestamp_field", "timestamp")
    fields = response_cfg.get("fields", {})
    timestamp_formats = response_cfg.get("timestamp_formats")

    rows: List[Dict[str, object]] = []
    if entry_type == "mapping":
        if not isinstance(data, Mapping):
            raise RuntimeError("response_expected_mapping")
        iterable = data.items()
    else:
        if not isinstance(data, Sequence):
            raise RuntimeError("response_expected_sequence")
        iterable = enumerate(data)

    for key, value in iterable:
        if timestamp_field == "key":
            ts_raw = str(key)
            record = value if isinstance(value, Mapping) else {}
        else:
            if not isinstance(value, Mapping):
                raise RuntimeError("response_entry_not_mapping")
            record = value
            ts_raw = str(record.get(timestamp_field, ""))
        dt = _normalize_timestamp(ts_raw, formats=timestamp_formats)
        if dt < start or dt > end:
            continue
        normalized = {
            "timestamp": dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "symbol": symbol.upper(),
            "tf": tf,
        }
        for target, source in fields.items():
            if source is None:
                if target in ("v", "spread"):
                    normalized[target] = 0.0
                continue
            if source not in record:
                raise RuntimeError(f"missing_field:{source}")
            normalized[target] = float(record[source])
        normalized.setdefault("v", 0.0)
        normalized.setdefault("spread", 0.0)
        rows.append(normalized)

    rows.sort(key=lambda item: item["timestamp"])
    return rows


def fetch_prices(
    symbol: str,
    tf: str,
    *,
    start: datetime,
    end: datetime,
    provider: Optional[str] = None,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    credentials_path: Path | str = DEFAULT_CREDENTIALS_PATH,
    anomaly_log_path: Path | str = DEFAULT_ANOMALY_LOG,
) -> List[Dict[str, object]]:
    """Fetch normalized bar records from the configured provider."""

    config = _load_config(config_path)
    provider_cfg = _select_provider(config, provider)
    required_credentials = provider_cfg.get("credentials", [])
    credentials = load_api_credentials(
        provider_cfg.name,
        required=required_credentials,
        path=credentials_path,
    )
    context = _format_context(
        symbol,
        tf,
        start=start,
        end=end,
        provider=provider_cfg,
        credentials=credentials,
    )
    url, headers = _build_url(provider_cfg, context)
    payload = _request_json(
        url,
        headers,
        provider=provider_cfg,
        anomaly_log_path=Path(anomaly_log_path),
    )
    data_section = _resolve_data_path(payload, provider_cfg, context)
    return _normalize_rows(
        data_section,
        provider=provider_cfg,
        context=context,
        symbol=symbol,
        tf=tf,
        start=start,
        end=end,
    )


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch price bars from REST API")
    parser.add_argument("--symbol", default="USDJPY")
    parser.add_argument("--tf", default="5m")
    parser.add_argument("--provider", default=None)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--credentials", default=str(DEFAULT_CREDENTIALS_PATH))
    parser.add_argument("--anomaly-log", default=str(DEFAULT_ANOMALY_LOG))
    parser.add_argument("--start-ts", default=None)
    parser.add_argument("--end-ts", default=None)
    parser.add_argument("--lookback-minutes", type=int, default=None)
    parser.add_argument("--out", default=None, help="Optional JSON output path")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    now = datetime.utcnow()
    config = _load_config(args.config)
    provider_cfg = _select_provider(config, args.provider)
    lookback_cfg = provider_cfg.get("lookback_minutes") or config.get("lookback_minutes", 60)
    lookback = args.lookback_minutes or int(lookback_cfg)

    end = parse_naive_utc_timestamp(args.end_ts) if args.end_ts else now
    start = parse_naive_utc_timestamp(args.start_ts) if args.start_ts else end - timedelta(minutes=lookback)

    rows = fetch_prices(
        args.symbol,
        args.tf,
        start=start,
        end=end,
        provider=provider_cfg.name,
        config_path=args.config,
        credentials_path=args.credentials,
        anomaly_log_path=args.anomaly_log,
    )

    summary = {
        "symbol": args.symbol.upper(),
        "tf": args.tf,
        "rows": len(rows),
        "start_ts": rows[0]["timestamp"] if rows else None,
        "end_ts": rows[-1]["timestamp"] if rows else None,
        "provider": provider_cfg.name,
    }

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as fh:
            json.dump(rows, fh, ensure_ascii=False, indent=2)
    else:
        print(json.dumps(rows, ensure_ascii=False))

    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
