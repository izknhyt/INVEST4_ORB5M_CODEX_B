"""Helpers for assembling the weekly observability payload."""

from __future__ import annotations

import csv
import statistics
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from scripts.utils_runs import RunRecord

SCHEMA_VERSION = "1.0.0"


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


@dataclass(frozen=True)
class LatencyRollupEntry:
    """Single aggregated latency sample."""

    window_start: datetime
    window_end: datetime
    count: int
    failure_count: int
    failure_rate: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float
    breach_flag: bool = False
    breach_streak: int = 0

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> Optional["LatencyRollupEntry"]:
        try:
            window_start = _parse_ts(row.get("hour_utc"))
            window_end = _parse_ts(row.get("window_end_utc"))
            count = int(float(row.get("count", 0)))
            failure_count = int(float(row.get("failure_count", 0)))
            failure_rate = float(row.get("failure_rate", 0.0) or 0.0)
            p50_ms = float(row.get("p50_ms", 0.0) or 0.0)
            p95_ms = float(row.get("p95_ms", 0.0) or 0.0)
            p99_ms = float(row.get("p99_ms", 0.0) or 0.0)
            max_ms = float(row.get("max_ms", 0.0) or 0.0)
            breach_streak = int(float(row.get("breach_streak", 0) or 0))
            raw_breach_flag = row.get("breach_flag")
            breach_flag = _parse_bool(raw_breach_flag) if raw_breach_flag is not None else failure_rate > 0
        except Exception:
            return None
        return cls(
            window_start=window_start,
            window_end=window_end,
            count=count,
            failure_count=failure_count,
            failure_rate=failure_rate,
            p50_ms=p50_ms,
            p95_ms=p95_ms,
            p99_ms=p99_ms,
            max_ms=max_ms,
            breach_flag=breach_flag,
            breach_streak=breach_streak,
        )


@dataclass(frozen=True)
class WeeklyPayloadContext:
    """Aggregated input artefacts required to build the weekly payload."""

    runs: Sequence[RunRecord]
    portfolio: Mapping[str, Any]
    latency_rollups: Sequence[LatencyRollupEntry]
    as_of: datetime
    sources: Mapping[str, str] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class WeeklyPayload:
    """Structured weekly payload with validation helpers."""

    schema_version: str
    generated_at: str
    week_start: str
    runs: List[Dict[str, Any]]
    portfolio: Dict[str, Any]
    latency: Dict[str, Any]
    alerts: List[Dict[str, Any]]
    sources: Dict[str, Any]
    metadata: Dict[str, Any]

    def ensure_complete(self) -> None:
        required_root = ["schema_version", "generated_at", "week_start", "runs", "portfolio", "latency"]
        for key in required_root:
            if getattr(self, key, None) in (None, []):
                raise ValueError(f"weekly payload missing required field: {key}")
        if not self.runs:
            raise ValueError("weekly payload requires at least one run entry")
        if "budget_status" not in self.portfolio:
            raise ValueError("portfolio summary missing budget_status")
        if "p95_ms" not in self.latency:
            raise ValueError("latency summary missing p95_ms")

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "week_start": self.week_start,
            "runs": self.runs,
            "portfolio": self.portfolio,
            "latency": self.latency,
            "alerts": self.alerts,
            "sources": self.sources,
        }
        if self.metadata:
            payload["metadata"] = self.metadata
        return payload


def load_latency_rollups(path: Path) -> List[LatencyRollupEntry]:
    if not path.exists():
        return []
    entries: List[LatencyRollupEntry] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            entry = LatencyRollupEntry.from_row(row)
            if entry is not None:
                entries.append(entry)
    return sorted(entries, key=lambda item: item.window_start)


def build(context: WeeklyPayloadContext) -> WeeklyPayload:
    week_start_dt = _week_start(context.as_of)
    runs_section = _build_runs_section(context.runs, week_start_dt)
    latency_section = _build_latency_section(context.latency_rollups, week_start_dt)
    portfolio_section = _build_portfolio_section(context.portfolio)
    alerts = _collect_alerts(latency_section, portfolio_section)
    metadata = dict(context.metadata)
    metadata.setdefault("generated_at", context.as_of.isoformat().replace("+00:00", "Z"))
    metadata.setdefault("week_start", week_start_dt.isoformat())

    payload = WeeklyPayload(
        schema_version=SCHEMA_VERSION,
        generated_at=context.as_of.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        week_start=week_start_dt.isoformat(),
        runs=runs_section,
        portfolio=portfolio_section,
        latency=latency_section,
        alerts=alerts,
        sources=dict(context.sources),
        metadata=metadata,
    )
    payload.ensure_complete()
    return payload


def _build_runs_section(records: Sequence[RunRecord], week_start: date) -> List[Dict[str, Any]]:
    week_start_dt = datetime.combine(week_start, datetime.min.time(), tzinfo=timezone.utc)
    week_end_dt = week_start_dt + timedelta(days=7)
    filtered: List[RunRecord] = []
    for record in records:
        record_ts = _parse_run_ts(record.timestamp)
        if record_ts is None or record_ts < week_start_dt or record_ts >= week_end_dt:
            continue
        filtered.append(record)
    if not filtered:
        filtered = list(records)

    def sort_key(item: RunRecord) -> float:
        return item.total_pips

    top_runs = sorted(filtered, key=sort_key, reverse=True)[:10]
    payload: List[Dict[str, Any]] = []
    for record in top_runs:
        entry: Dict[str, Any] = {
            "run_id": record.run_id,
            "symbol": record.symbol,
            "mode": record.mode,
            "timestamp": _format_ts(_parse_run_ts(record.timestamp) or week_start_dt),
            "trades": record.trades,
            "wins": record.wins,
            "total_pips": round(record.total_pips, 6),
            "win_rate": round(record.win_rate, 6),
        }
        if record.sharpe is not None:
            entry["sharpe"] = round(record.sharpe, 6)
        if record.max_drawdown is not None:
            entry["max_drawdown"] = round(record.max_drawdown, 6)
        if record.pnl_per_trade is not None:
            entry["pnl_per_trade"] = round(record.pnl_per_trade, 6)
        payload.append(entry)
    return payload


def _build_latency_section(entries: Sequence[LatencyRollupEntry], week_start: date) -> Dict[str, Any]:
    if not entries:
        return {
            "p50_ms": 0.0,
            "p95_ms": 0.0,
            "p99_ms": 0.0,
            "max_ms": 0.0,
            "breach_count": 0,
            "breaches": [],
            "samples": 0,
        }
    week_start_dt = datetime.combine(week_start, datetime.min.time(), tzinfo=timezone.utc)
    week_end_dt = week_start_dt + timedelta(days=7)
    recent = [entry for entry in entries if week_start_dt <= entry.window_end <= week_end_dt]
    if not recent:
        recent = list(entries)
    p50_values = [entry.p50_ms for entry in recent]
    p95_values = [entry.p95_ms for entry in recent]
    p99_values = [entry.p99_ms for entry in recent]
    max_values = [entry.max_ms for entry in recent]
    breach_candidates = [
        entry
        for entry in sorted(recent, key=lambda item: item.p95_ms, reverse=True)[:5]
        if entry.breach_flag or entry.failure_rate > 0
    ]
    breaches = [
        {
            "hour_utc": _format_ts(entry.window_start),
            "p95_ms": round(entry.p95_ms, 3),
            "failure_rate": round(entry.failure_rate, 6),
            "count": entry.count,
            "breach_streak": entry.breach_streak,
        }
        for entry in breach_candidates
    ]
    breach_count = sum(1 for entry in recent if entry.breach_flag or entry.failure_rate > 0)
    return {
        "p50_ms": round(statistics.fmean(p50_values), 3) if p50_values else 0.0,
        "p95_ms": round(max(p95_values), 3) if p95_values else 0.0,
        "p99_ms": round(max(p99_values), 3) if p99_values else 0.0,
        "max_ms": round(max(max_values), 3) if max_values else 0.0,
        "breach_count": breach_count,
        "breaches": breaches,
        "samples": sum(entry.count for entry in recent),
    }


def _build_portfolio_section(portfolio: Mapping[str, Any]) -> Dict[str, Any]:
    categories = portfolio.get("category_utilisation") or []
    category_payload: List[Dict[str, Any]] = []
    severity_order = {"ok": 0, "warning": 1, "breach": 2}
    worst_status = "ok"
    for entry in categories:
        category_status = entry.get("budget_status") or entry.get("status") or "ok"
        worst_status = _max_status(worst_status, category_status, severity_order)
        category_payload.append(
            {
                "category": entry.get("category"),
                "utilisation_pct": entry.get("utilisation_pct"),
                "budget_status": category_status,
                "headroom_pct": entry.get("headroom_pct"),
            }
        )
    gross = portfolio.get("gross_exposure") or {}
    drawdowns = portfolio.get("drawdowns") or {}
    aggregate_drawdown = (drawdowns.get("aggregate") or {}).get("max_drawdown_pct")
    payload = {
        "budget_status": worst_status,
        "category_utilisation": category_payload,
        "gross_exposure_pct": gross.get("current_pct"),
        "headroom_pct": gross.get("headroom_pct"),
        "drawdown_pct": aggregate_drawdown,
    }
    generated_at = portfolio.get("generated_at")
    if generated_at:
        payload["generated_at"] = generated_at
    return payload


def _collect_alerts(latency: Mapping[str, Any], portfolio: Mapping[str, Any]) -> List[Dict[str, Any]]:
    alerts: List[Dict[str, Any]] = []
    if latency.get("breach_count", 0):
        alerts.append(
            {
                "id": "latency_breach",
                "severity": "warning",
                "message": f"{latency['breach_count']} latency windows reported failures",
                "evidence_path": "latency_rollup",
            }
        )
    status = portfolio.get("budget_status")
    if status in {"warning", "breach"}:
        severity = "critical" if status == "breach" else "warning"
        alerts.append(
            {
                "id": "portfolio_budget",
                "severity": severity,
                "message": f"portfolio budget status is {status}",
                "evidence_path": "portfolio_summary",
            }
        )
    return alerts


def _parse_ts(text: Optional[str]) -> datetime:
    if not text:
        raise ValueError("timestamp missing")
    cleaned = text.strip()
    if not cleaned:
        raise ValueError("timestamp missing")
    return datetime.fromisoformat(cleaned.replace("Z", "+00:00")).astimezone(timezone.utc)


def _parse_run_ts(text: Optional[str]) -> Optional[datetime]:
    if not text:
        return None
    cleaned = text.strip()
    if not cleaned:
        return None
    try:
        dt = datetime.strptime(cleaned, "%Y%m%d_%H%M%S")
    except ValueError:
        return None
    return dt.replace(tzinfo=timezone.utc)


def _format_ts(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _week_start(moment: datetime) -> date:
    utc = moment.astimezone(timezone.utc)
    return (utc.date() - timedelta(days=utc.weekday()))


def _max_status(current: str, new: str, order: Mapping[str, int]) -> str:
    return current if order.get(current, 0) >= order.get(new, 0) else new
