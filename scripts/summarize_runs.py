from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.utils import yaml_compat as yaml
from scripts.utils_runs import RunRecord, load_runs_index


COMPONENT_RUNS = "runs"
COMPONENT_BENCHMARKS = "benchmarks"
COMPONENT_PORTFOLIO = "portfolio"
COMPONENT_HEALTH = "health"
ALL_COMPONENTS = {
    COMPONENT_RUNS,
    COMPONENT_BENCHMARKS,
    COMPONENT_PORTFOLIO,
    COMPONENT_HEALTH,
}


@dataclass(frozen=True)
class SummaryPaths:
    runs_root: Path
    benchmark_summary: Path
    portfolio_summary: Path
    health_checks: Path

    @property
    def runs_index(self) -> Path:
        return self.runs_root / "index.csv"


def _resolve_rooted_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    if not path.is_absolute():
        return ROOT / path
    return path


def _load_json(path: Path) -> Any:
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _summarize_run_records(records: Sequence[RunRecord]) -> Dict[str, Any]:
    totals = {
        "trades": 0,
        "wins": 0,
        "total_pips": 0.0,
    }
    groups: Dict[tuple[str, str], Dict[str, Any]] = {}
    for record in records:
        totals["trades"] += record.trades
        totals["wins"] += record.wins
        totals["total_pips"] += record.total_pips
        key = (record.symbol, record.mode)
        bucket = groups.setdefault(
            key,
            {
                "symbol": record.symbol,
                "mode": record.mode,
                "runs": 0,
                "trades": 0,
                "wins": 0,
                "total_pips": 0.0,
            },
        )
        bucket["runs"] += 1
        bucket["trades"] += record.trades
        bucket["wins"] += record.wins
        bucket["total_pips"] += record.total_pips
    win_rate = (totals["wins"] / totals["trades"]) if totals["trades"] else 0.0
    for bucket in groups.values():
        trades = bucket["trades"]
        bucket["win_rate"] = (bucket["wins"] / trades) if trades else 0.0
    top_runs = sorted(records, key=lambda r: r.total_pips, reverse=True)[:5]
    top_payload = [
        {
            "run_id": r.run_id,
            "symbol": r.symbol,
            "mode": r.mode,
            "total_pips": r.total_pips,
            "trades": r.trades,
            "wins": r.wins,
            "win_rate": r.win_rate,
        }
        for r in top_runs
    ]
    return {
        "total_runs": len(records),
        "totals": {
            **totals,
            "win_rate": win_rate,
        },
        "by_symbol_mode": sorted(groups.values(), key=lambda b: (b["symbol"], b["mode"])),
        "top_runs": top_payload,
    }


def summarize_runs(index_path: Path) -> Dict[str, Any]:
    if not index_path.exists():
        return {
            "source": str(index_path),
            "available": False,
            "reason": "index.csv not found",
        }
    records = load_runs_index(index_path)
    summary = _summarize_run_records(records)
    summary.update({
        "source": str(index_path),
        "available": True,
    })
    return summary


def summarize_benchmarks(summary_path: Path) -> Dict[str, Any]:
    data = _load_json(summary_path)
    if data is None:
        return {
            "source": str(summary_path),
            "available": False,
            "reason": "benchmark_summary.json not found",
        }
    rolling_entries = data.get("rolling") or []
    rolling = [
        {
            "window": entry.get("window"),
            "trades": entry.get("trades", 0),
            "wins": entry.get("wins", 0),
            "win_rate": entry.get("win_rate", 0.0),
            "total_pips": entry.get("total_pips", 0.0),
            "sharpe": entry.get("sharpe"),
            "max_drawdown": entry.get("max_drawdown"),
        }
        for entry in sorted(rolling_entries, key=lambda item: item.get("window", 0))
    ]
    warnings = data.get("warnings") or []
    threshold_alerts = data.get("threshold_alerts") or []
    status = "ok" if not warnings and not threshold_alerts else "warning"
    return {
        "source": str(summary_path),
        "available": True,
        "status": status,
        "generated_at": data.get("generated_at"),
        "symbol": data.get("symbol"),
        "mode": data.get("mode"),
        "baseline": data.get("baseline", {}),
        "rolling": rolling,
        "warnings": warnings,
        "threshold_alerts": threshold_alerts,
    }


def summarize_portfolio(portfolio_path: Path) -> Dict[str, Any]:
    data = _load_json(portfolio_path)
    if data is None:
        return {
            "source": str(portfolio_path),
            "available": False,
            "reason": "portfolio_summary.json not found",
        }
    categories = data.get("category_utilisation") or []
    category_payload = [
        {
            "category": entry.get("category"),
            "utilisation_pct": entry.get("utilisation_pct"),
            "cap_pct": entry.get("cap_pct"),
            "headroom_pct": entry.get("headroom_pct"),
            "utilisation_ratio": entry.get("utilisation_ratio"),
            "status": _categorize_ratio(entry.get("utilisation_ratio")),
        }
        for entry in categories
    ]
    gross = data.get("gross_exposure") or {}
    return {
        "source": str(portfolio_path),
        "available": True,
        "category_utilisation": category_payload,
        "gross_exposure": gross,
        "generated_at": data.get("generated_at"),
    }


def _categorize_ratio(ratio: Optional[float]) -> str:
    if ratio is None:
        return "unknown"
    if ratio >= 1.0:
        return "breach"
    if ratio >= 0.85:
        return "warning"
    return "ok"


def summarize_health(health_path: Path, recent_limit: int = 5) -> Dict[str, Any]:
    data = _load_json(health_path)
    if data is None:
        return {
            "source": str(health_path),
            "available": False,
            "reason": "state_checks.json not found",
        }
    entries: List[Dict[str, Any]] = [entry for entry in data if isinstance(entry, dict)]
    entries.sort(key=lambda item: _safe_parse_dt(item.get("checked_at")))
    recent = entries[-recent_limit:]
    latest = recent[-1] if recent else None
    if latest:
        warnings = latest.get("warnings") or []
        latest_payload = {
            "checked_at": latest.get("checked_at"),
            "warning_count": len(warnings),
            "warnings": warnings,
            "metrics": latest.get("metrics", {}),
            "state_path": latest.get("state_path"),
        }
    else:
        latest_payload = None
    recent_payload = [
        {
            "checked_at": entry.get("checked_at"),
            "warning_count": len(entry.get("warnings") or []),
        }
        for entry in recent
    ]
    status = "ok"
    if latest_payload and latest_payload["warning_count"]:
        status = "warning"
    return {
        "source": str(health_path),
        "available": True,
        "status": status,
        "latest": latest_payload,
        "recent": recent_payload,
        "total_checks": len(entries),
    }


def _safe_parse_dt(value: Optional[str]) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    text = value
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


def load_config(path: Optional[str]) -> Dict[str, Any]:
    if not path:
        return {}
    config_path = _resolve_rooted_path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"config file not found: {config_path}")
    with config_path.open(encoding="utf-8") as f:
        loaded = yaml.safe_load(f.read())
    return loaded or {}


def _parse_component_list(raw: Optional[Iterable[str]]) -> List[str]:
    components: List[str] = []
    if not raw:
        return components
    for item in raw:
        if item is None:
            continue
        parts = [part.strip() for part in str(item).split(",") if part.strip()]
        components.extend(parts)
    return components


def resolve_includes(cli_includes: Optional[Iterable[str]], config: Dict[str, Any]) -> List[str]:
    config_includes = config.get("include")
    candidates = _parse_component_list(cli_includes) or _parse_component_list(config_includes)
    if not candidates:
        return sorted(ALL_COMPONENTS)
    invalid = [name for name in candidates if name not in ALL_COMPONENTS]
    if invalid:
        raise ValueError(f"unknown components requested: {', '.join(invalid)}")
    seen: Dict[str, None] = {}
    ordered = []
    for name in candidates:
        if name not in seen:
            seen[name] = None
            ordered.append(name)
    return ordered


def build_summary(paths: SummaryPaths, includes: Sequence[str], *, generated_at: Optional[str] = None) -> Dict[str, Any]:
    components: Dict[str, Any] = {}
    include_set = set(includes)
    if COMPONENT_RUNS in include_set:
        components[COMPONENT_RUNS] = summarize_runs(paths.runs_index)
    if COMPONENT_BENCHMARKS in include_set:
        components[COMPONENT_BENCHMARKS] = summarize_benchmarks(paths.benchmark_summary)
    if COMPONENT_PORTFOLIO in include_set:
        components[COMPONENT_PORTFOLIO] = summarize_portfolio(paths.portfolio_summary)
    if COMPONENT_HEALTH in include_set:
        components[COMPONENT_HEALTH] = summarize_health(paths.health_checks)
    timestamp = generated_at or datetime.now(timezone.utc).isoformat()
    return {
        "type": "benchmark_weekly_summary",
        "generated_at": timestamp,
        "sources": {
            "runs_index": str(paths.runs_index),
            "benchmark_summary": str(paths.benchmark_summary),
            "portfolio_summary": str(paths.portfolio_summary),
            "health_checks": str(paths.health_checks),
        },
        "includes": list(includes),
        "components": components,
    }


def dispatch_webhooks(
    payload: Dict[str, Any],
    destinations: Sequence[Dict[str, Any]],
    *,
    fail_on_error: bool = False,
    dry_run: bool = False,
) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for destination in destinations:
        url = destination.get("url")
        timeout = float(destination.get("timeout", 5.0))
        headers = destination.get("headers") or {}
        result: Dict[str, Any] = {"url": url, "timeout": timeout}
        if not url:
            result["status"] = "error"
            result["error"] = "missing webhook url"
            results.append(result)
            if fail_on_error:
                raise RuntimeError("webhook destination missing url")
            continue
        if dry_run:
            result["status"] = "skipped"
            results.append(result)
            continue
        try:
            status_code, body = _post_json(url, payload, timeout=timeout, headers=headers)
        except Exception as exc:  # noqa: BLE001 - deliberate catch to control webhook failures
            result["status"] = "error"
            result["error"] = str(exc)
            results.append(result)
            if fail_on_error:
                raise
            continue
        result["status"] = "ok" if 200 <= status_code < 300 else "error"
        result["status_code"] = status_code
        if body:
            result["body"] = body
        results.append(result)
        if fail_on_error and result["status"] == "error":
            raise RuntimeError(f"webhook {url} returned status {status_code}")
    return results


def _post_json(url: str, payload: Dict[str, Any], *, timeout: float, headers: Dict[str, str]) -> tuple[int, str]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request_headers = {"Content-Type": "application/json", "User-Agent": "summarize-runs/1.0"}
    request_headers.update(headers)
    req = Request(url, data=data, headers=request_headers, method="POST")
    try:
        with urlopen(req, timeout=timeout) as response:
            status = getattr(response, "status", None)
            if status is None and hasattr(response, "getcode"):
                status = response.getcode()
            body_bytes = response.read() if hasattr(response, "read") else b""
    except HTTPError as err:
        body_bytes = err.read() if hasattr(err, "read") else b""
        return err.code, body_bytes.decode("utf-8", "ignore")
    except URLError as err:
        raise RuntimeError(str(err)) from err
    body_text = body_bytes.decode("utf-8", "ignore") if body_bytes else ""
    return int(status or 0), body_text


def resolve_webhooks(
    cli_urls: Optional[Iterable[str]],
    config: Dict[str, Any],
    default_timeout: float,
) -> List[Dict[str, Any]]:
    config_destinations = config.get("destinations") or {}
    config_webhooks = config_destinations.get("webhooks") or []
    destinations: List[Dict[str, Any]] = []
    for entry in config_webhooks:
        if not isinstance(entry, dict):
            continue
        if "url" not in entry:
            continue
        destination = {
            "url": entry["url"],
            "timeout": entry.get("timeout", default_timeout),
            "headers": entry.get("headers") or {},
        }
        destinations.append(destination)
    for url in cli_urls or []:
        destinations.append({"url": url, "timeout": default_timeout, "headers": {}})
    return destinations


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Aggregate benchmark and health summaries for notification.")
    parser.add_argument("--runs-dir", default="runs", help="Root directory containing runs/index.csv (deprecated alias).")
    parser.add_argument("--runs-root", default=None, help="Root directory containing runs/index.csv.")
    parser.add_argument(
        "--json-out",
        dest="json_out",
        default=None,
        help="Write the resulting payload (with delivery metadata) to this path.",
    )
    parser.add_argument(
        "--out-json",
        dest="json_out",
        help="Alias for --json-out to support legacy CLI usage.",
    )
    parser.add_argument(
        "--benchmark-summary",
        default="reports/benchmark_summary.json",
        help="Path to reports/benchmark_summary.json.",
    )
    parser.add_argument(
        "--portfolio-summary",
        default="reports/portfolio_summary.json",
        help="Path to reports/portfolio_summary.json.",
    )
    parser.add_argument(
        "--health-checks",
        default="ops/health/state_checks.json",
        help="Path to ops/health/state_checks.json.",
    )
    parser.add_argument(
        "--include",
        action="append",
        choices=sorted(ALL_COMPONENTS),
        help="Component(s) to include. When omitted all components are collected.",
    )
    parser.add_argument("--config", help="Optional YAML config controlling includes and destinations.")
    parser.add_argument(
        "--webhook-url",
        action="append",
        help="Webhook URL(s) to deliver the payload to. Can be provided multiple times.",
    )
    parser.add_argument(
        "--webhook-timeout",
        type=float,
        default=5.0,
        help="Timeout in seconds when posting to webhook destinations.",
    )
    parser.add_argument(
        "--dry-run-webhook",
        action="store_true",
        help="Skip webhook delivery while still generating the payload.",
    )
    parser.add_argument(
        "--fail-on-webhook-error",
        action="store_true",
        help="Raise an error if any webhook call fails (default: log and continue).",
    )
    parser.add_argument(
        "--payload-type",
        default="benchmark_weekly_summary",
        help="Override the payload type identifier.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        args = parse_args(argv)
        config = load_config(args.config)
        includes = resolve_includes(args.include, config)
    except Exception as exc:  # noqa: BLE001 - convert to CLI exit
        print(f"error: {exc}", file=sys.stderr)
        return 1

    runs_root_arg = args.runs_root or args.runs_dir
    paths = SummaryPaths(
        runs_root=_resolve_rooted_path(runs_root_arg),
        benchmark_summary=_resolve_rooted_path(args.benchmark_summary),
        portfolio_summary=_resolve_rooted_path(args.portfolio_summary),
        health_checks=_resolve_rooted_path(args.health_checks),
    )

    payload = build_summary(paths, includes)
    payload["type"] = args.payload_type
    destinations = resolve_webhooks(args.webhook_url, config, args.webhook_timeout)
    payload["destinations"] = {"webhooks": [dest["url"] for dest in destinations]}

    fail_on_error = bool(args.fail_on_webhook_error or (config.get("destinations", {}).get("fail_on_error")))
    dry_run = bool(args.dry_run_webhook or (config.get("destinations", {}).get("dry_run")))
    webhook_results = dispatch_webhooks(payload, destinations, fail_on_error=fail_on_error, dry_run=dry_run)
    output_payload = dict(payload)
    if webhook_results:
        output_payload["webhook_delivery"] = webhook_results

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(output_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(output_payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
