"""Data loaders that power the observability dashboard pipeline."""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import NormalDist
from typing import Dict, List, Mapping, Optional, Tuple


@dataclass
class EVSnapshot:
    """Represents a single EV state export."""

    timestamp: datetime
    alpha: float
    beta: float
    decay: float
    confidence: float
    win_rate_mean: Optional[float]
    win_rate_lcb: Optional[float]

    def to_dict(self) -> Dict[str, object]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "alpha": self.alpha,
            "beta": self.beta,
            "decay": self.decay,
            "confidence": self.confidence,
            "win_rate_mean": self.win_rate_mean,
            "win_rate_lcb": self.win_rate_lcb,
        }


@dataclass
class SlippageSnapshot:
    """Captures slippage coefficients or realised execution stats."""

    timestamp: datetime
    coefficients: Dict[str, float]
    ewma_alpha: Optional[float]
    curve: Optional[Dict[str, Dict[str, float]]]
    source: str

    def to_dict(self) -> Dict[str, object]:
        payload: Dict[str, object] = {
            "timestamp": self.timestamp.isoformat(),
            "coefficients": self.coefficients,
            "source": self.source,
        }
        if self.ewma_alpha is not None:
            payload["ewma_alpha"] = self.ewma_alpha
        if self.curve is not None:
            payload["curve"] = self.curve
        return payload


@dataclass
class TurnoverSnapshot:
    """Summarises trade turnover for a completed run."""

    run_id: str
    timestamp: datetime
    trades: int
    wins: Optional[int]
    win_rate: Optional[float]
    avg_trades_per_day: Optional[float]
    avg_trades_active_day: Optional[float]
    start_date: Optional[str]
    end_date: Optional[str]

    def to_dict(self) -> Dict[str, object]:
        return {
            "run_id": self.run_id,
            "timestamp": self.timestamp.isoformat(),
            "trades": self.trades,
            "wins": self.wins,
            "win_rate": self.win_rate,
            "avg_trades_per_day": self.avg_trades_per_day,
            "avg_trades_active_day": self.avg_trades_active_day,
            "start_date": self.start_date,
            "end_date": self.end_date,
        }


def _parse_state_timestamp(path: Path) -> datetime:
    stem = path.stem
    tokens = [token for token in stem.split("_") if token.isdigit()]
    if len(tokens) >= 2 and len(tokens[0]) == 8:
        ts_raw = f"{tokens[0]}{tokens[1][:6]}"
    else:
        cleaned = "".join(ch for ch in stem if ch.isdigit())
        if len(cleaned) < 14:
            raise ValueError(f"Cannot extract timestamp from {path.name}")
        ts_raw = cleaned[:14]
    dt = datetime.strptime(ts_raw, "%Y%m%d%H%M%S")
    return dt.replace(tzinfo=timezone.utc)


def _read_json(path: Path) -> Dict[str, object]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _normal_approx_lcb(alpha: float, beta: float, confidence: float) -> float:
    total = alpha + beta
    if total <= 0:
        return 0.0
    mean = alpha / total
    if total <= 1:
        variance = mean * (1.0 - mean)
    else:
        variance = (alpha * beta) / ((total ** 2) * (total + 1))
    std = math.sqrt(max(variance, 0.0))
    conf = max(0.5, min(confidence, 0.999))
    z_value = abs(NormalDist().inv_cdf(0.5 + conf / 2.0))
    lcb = mean - z_value * std
    return max(0.0, min(1.0, lcb))


def _list_state_files(archive_dir: Path) -> List[Path]:
    if not archive_dir.exists():
        raise FileNotFoundError(f"EV archive directory not found: {archive_dir}")
    files = sorted(archive_dir.glob("*.json"), key=_parse_state_timestamp)
    if not files:
        raise ValueError(f"No EV state exports discovered under {archive_dir}")
    return files


def load_ev_history(archive_dir: Path, *, limit: Optional[int] = None) -> List[EVSnapshot]:
    files = _list_state_files(archive_dir)
    snapshots: List[EVSnapshot] = []
    selected = files if limit is None else files[-limit:]
    for path in selected:
        payload = _read_json(path)
        timestamp = _parse_state_timestamp(path)
        ev_global = payload.get("ev_global", {})
        alpha = float(ev_global.get("alpha", 0.0))
        beta = float(ev_global.get("beta", 0.0))
        decay = float(ev_global.get("decay", 0.0)) if "decay" in ev_global else 0.0
        confidence = float(ev_global.get("conf", 0.95))
        total = alpha + beta
        win_mean = alpha / total if total > 0 else None
        win_lcb = _normal_approx_lcb(alpha, beta, confidence) if total > 0 else None
        snapshots.append(
            EVSnapshot(
                timestamp=timestamp,
                alpha=alpha,
                beta=beta,
                decay=decay,
                confidence=confidence,
                win_rate_mean=win_mean,
                win_rate_lcb=win_lcb,
            )
        )
    return snapshots


def load_state_slippage(archive_dir: Path, *, limit: Optional[int] = None) -> List[SlippageSnapshot]:
    files = _list_state_files(archive_dir)
    snapshots: List[SlippageSnapshot] = []
    selected = files if limit is None else files[-limit:]
    for path in selected:
        payload = _read_json(path)
        timestamp = _parse_state_timestamp(path)
        slip = payload.get("slip") or {}
        coeffs_raw = slip.get("a") or {}
        coefficients: Dict[str, float] = {}
        for band, value in coeffs_raw.items():
            try:
                coefficients[str(band)] = float(value)
            except (TypeError, ValueError):
                continue
        curve = slip.get("curve") if isinstance(slip.get("curve"), Mapping) else None
        ewma_alpha = slip.get("ewma_alpha")
        try:
            ewma_alpha_value = float(ewma_alpha) if ewma_alpha is not None else None
        except (TypeError, ValueError):
            ewma_alpha_value = None
        snapshots.append(
            SlippageSnapshot(
                timestamp=timestamp,
                coefficients=coefficients,
                ewma_alpha=ewma_alpha_value,
                curve=curve if curve is not None else None,
                source="state_archive",
            )
        )
    return snapshots


def load_execution_slippage(telemetry_path: Path) -> List[SlippageSnapshot]:
    if not telemetry_path.exists():
        raise FileNotFoundError(f"Portfolio telemetry snapshot not found: {telemetry_path}")
    payload = _read_json(telemetry_path)
    execution = payload.get("execution_health") or {}
    snapshots: List[SlippageSnapshot] = []
    timestamp = datetime.fromtimestamp(telemetry_path.stat().st_mtime, tz=timezone.utc)
    if isinstance(execution, Mapping):
        for strategy, stats in execution.items():
            if not isinstance(stats, Mapping):
                continue
            coefficients: Dict[str, float] = {}
            for key in ("slippage_bps", "reject_rate"):
                value = stats.get(key)
                try:
                    coefficients[key] = float(value)
                except (TypeError, ValueError):
                    continue
            if coefficients:
                snapshots.append(
                    SlippageSnapshot(
                        timestamp=timestamp,
                        coefficients=coefficients,
                        ewma_alpha=None,
                        curve=None,
                        source=f"execution:{strategy}",
                    )
                )
    return snapshots


def _load_daily_csv(path: Path) -> Tuple[int, int, Optional[str], Optional[str]]:
    if not path.exists():
        raise FileNotFoundError(f"Daily summary not found: {path}")
    total_fills = 0
    total_days = 0
    active_days = 0
    first_date: Optional[str] = None
    last_date: Optional[str] = None
    with path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            total_days += 1
            date_value = row.get("date")
            if date_value and not first_date:
                first_date = date_value
            if date_value:
                last_date = date_value
            try:
                fills = int(float(row.get("fills", "0") or 0))
            except (TypeError, ValueError):
                fills = 0
            total_fills += fills
            if fills > 0:
                active_days += 1
    return total_fills, max(total_days, 0), active_days, first_date, last_date


def load_turnover_metrics(
    runs_root: Path,
    *,
    limit: Optional[int] = None,
    daily_dir_name: str = "daily.csv",
) -> List[TurnoverSnapshot]:
    index_path = runs_root / "index.csv"
    if not index_path.exists():
        raise FileNotFoundError(f"Run index not found: {index_path}")
    snapshots: List[TurnoverSnapshot] = []
    with index_path.open("r", encoding="utf-8") as handle:
        reader = list(csv.DictReader(handle))
    rows = reader if limit is None else reader[-limit:]
    for row in rows:
        run_id = row.get("run_id") or row.get("run_dir")
        if not run_id:
            continue
        run_dir = row.get("run_dir") or f"runs/{run_id}"
        run_path = Path(run_dir)
        if not run_path.is_absolute():
            parts = run_path.parts
            if parts and parts[0] == runs_root.name:
                run_path = runs_root.joinpath(*parts[1:])
            else:
                run_path = runs_root / run_path
        daily_path = run_path / daily_dir_name
        try:
            total_fills, total_days, active_days, start_date, end_date = _load_daily_csv(daily_path)
        except FileNotFoundError:
            total_fills = 0
            total_days = 0
            active_days = 0
            start_date = None
            end_date = None
        trades = _to_int(row.get("trades"))
        wins = _to_int(row.get("wins"))
        win_rate = _to_float(row.get("win_rate"))
        timestamp_str = row.get("timestamp") or ""
        try:
            timestamp = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc)
        except ValueError:
            timestamp = datetime.fromtimestamp(index_path.stat().st_mtime, tz=timezone.utc)
        avg_trades_per_day = (
            total_fills / total_days if total_days > 0 else None
        )
        avg_trades_active_day = (
            total_fills / active_days if active_days > 0 else None
        )
        snapshots.append(
            TurnoverSnapshot(
                run_id=str(run_id),
                timestamp=timestamp,
                trades=trades if trades is not None else total_fills,
                wins=wins,
                win_rate=win_rate,
                avg_trades_per_day=avg_trades_per_day,
                avg_trades_active_day=avg_trades_active_day,
                start_date=start_date,
                end_date=end_date,
            )
        )
    return snapshots


def _to_int(value: Optional[str]) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _to_float(value: Optional[str]) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
