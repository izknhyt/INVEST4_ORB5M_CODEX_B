"""
Feature Store (5m mode) — minimal calculations for ATR, ADX, OR width, RV, bands
NOTE: Placeholder computations; replace with vetted implementations during integration.
"""
from __future__ import annotations
import math
from collections import deque
from typing import Deque, Dict, Any, Tuple, List

def true_range(h, l, pc):
    return max(h-l, abs(h-pc), abs(l-pc))

def atr(bars: List[Dict[str, float]], period: int = 14) -> float:
    if len(bars) < period+1: return float("nan")
    trs = [true_range(bars[i]["h"], bars[i]["l"], bars[i-1]["c"]) for i in range(1, period+1)]
    return sum(trs)/period

def adx(bars: List[Dict[str, float]], period: int = 14) -> float:
    # Simplified ADX (Wilder). For skeleton purposes.
    if len(bars) < period+1: return float("nan")
    plus_dm = []; minus_dm = []; tr = []
    for i in range(1, period+1):
        up = bars[i]["h"] - bars[i-1]["h"]
        dn = bars[i-1]["l"] - bars[i]["l"]
        plus_dm.append(max(up, 0.0) if up > dn else 0.0)
        minus_dm.append(max(dn, 0.0) if dn > up else 0.0)
        tr.append(true_range(bars[i]["h"], bars[i]["l"], bars[i-1]["c"]))
    atrv = sum(tr)/period
    if atrv == 0: return 0.0
    plus_di = (sum(plus_dm)/period)/atrv * 100.0
    minus_di = (sum(minus_dm)/period)/atrv * 100.0
    dx = abs(plus_di - minus_di) / max(plus_di + minus_di, 1e-9) * 100.0
    return dx  # This is an approximation of ADX for skeleton

def opening_range(bars: List[Dict[str,float]], n: int = 6) -> Tuple[float,float]:
    if len(bars) < n: return (float("nan"), float("nan"))
    window = bars[:n]
    return (max(b["h"] for b in window), min(b["l"] for b in window))

def realized_vol(bars: List[Dict[str, float]], n: int = 12) -> float:
    if len(bars) < n+1: return float("nan")
    rsq = 0.0
    for i in range(1, n+1):
        r = math.log(bars[i]["c"]/bars[i-1]["c"])
        rsq += r*r
    return math.sqrt(rsq)*math.sqrt(288)  # 5m bars per day ~288; rough annualization proxy

def band(value: float, cuts: List[float], labels: List[str]) -> str:
    for c, lab in zip(cuts, labels):
        if value <= c: return lab
    return labels[-1]
