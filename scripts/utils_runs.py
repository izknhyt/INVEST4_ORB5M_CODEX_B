from __future__ import annotations
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Any


@dataclass
class RunRecord:
    run_id: str
    run_dir: str
    timestamp: str
    symbol: str
    mode: str
    equity: float
    or_n: int | None
    k_tp: float | None
    k_sl: float | None
    threshold_lcb: float | None
    min_or_atr: float | None
    allow_low_rv: bool
    allowed_sessions: str | None
    warmup: int | None
    trades: int
    wins: int
    total_pips: float
    sharpe: float | None = None
    max_drawdown: float | None = None
    pnl_per_trade: float | None = None

    @property
    def win_rate(self) -> float:
        return (self.wins / self.trades) if self.trades else 0.0


def load_runs_index(path: Path = Path("runs/index.csv")) -> List[RunRecord]:
    records: List[RunRecord] = []
    if not path.exists():
        return records
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                record = RunRecord(
                    run_id=row.get("run_id", ""),
                    run_dir=row.get("run_dir", ""),
                    timestamp=row.get("timestamp", ""),
                    symbol=row.get("symbol", ""),
                    mode=row.get("mode", ""),
                    equity=float(row.get("equity")) if row.get("equity") else 0.0,
                    or_n=int(row.get("or_n")) if row.get("or_n") else None,
                    k_tp=float(row.get("k_tp")) if row.get("k_tp") else None,
                    k_sl=float(row.get("k_sl")) if row.get("k_sl") else None,
                    threshold_lcb=float(row.get("threshold_lcb")) if row.get("threshold_lcb") else None,
                    min_or_atr=float(row.get("min_or_atr")) if row.get("min_or_atr") else None,
                    allow_low_rv=row.get("allow_low_rv", "False") == "True",
                    allowed_sessions=row.get("allowed_sessions"),
                    warmup=int(row.get("warmup")) if row.get("warmup") else None,
                    trades=int(float(row.get("trades"))) if row.get("trades") else 0,
                    wins=int(float(row.get("wins"))) if row.get("wins") else 0,
                    total_pips=float(row.get("total_pips")) if row.get("total_pips") else 0.0,
                    sharpe=float(row.get("sharpe")) if row.get("sharpe") else None,
                    max_drawdown=float(row.get("max_drawdown")) if row.get("max_drawdown") else None,
                    pnl_per_trade=float(row.get("pnl_per_trade")) if row.get("pnl_per_trade") else None,
                )
            except Exception:
                continue
            records.append(record)
    return records
