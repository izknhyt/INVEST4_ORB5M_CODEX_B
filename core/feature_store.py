"""
Feature Store (5m mode) — minimal calculations for ATR, ADX, OR width, RV, bands
NOTE: Placeholder computations; replace with vetted implementations during integration.
"""
from __future__ import annotations

import math
from typing import Mapping, Sequence, Tuple


Bar = Mapping[str, float]
NAN = math.nan


def true_range(high: float, low: float, prev_close: float) -> float:
    """Return the Wilder true range for the provided bar values."""

    return max(high - low, abs(high - prev_close), abs(low - prev_close))


def atr(bars: Sequence[Bar], period: int = 14) -> float:
    """Compute a simplified average true range; NaN if the window is incomplete."""

    if len(bars) < period + 1:
        # Require a previous close and ``period`` bars to compute ATR.
        return NAN

    trs = [
        true_range(bars[i]["h"], bars[i]["l"], bars[i - 1]["c"])
        for i in range(1, period + 1)
    ]
    return sum(trs) / period


def adx(bars: Sequence[Bar], period: int = 14) -> float:
    """Approximate the ADX using Wilder smoothing; NaN when insufficient data."""

    if len(bars) < period + 1:
        # ADX needs the previous close and ``period`` bars to form directional moves.
        return NAN

    plus_dm: list[float] = []
    minus_dm: list[float] = []
    tr: list[float] = []

    for i in range(1, period + 1):
        up = bars[i]["h"] - bars[i - 1]["h"]
        dn = bars[i - 1]["l"] - bars[i]["l"]
        plus_dm.append(max(up, 0.0) if up > dn else 0.0)
        minus_dm.append(max(dn, 0.0) if dn > up else 0.0)
        tr.append(true_range(bars[i]["h"], bars[i]["l"], bars[i - 1]["c"]))

    atrv = sum(tr) / period
    if atrv == 0:
        # Avoid division by zero when the true range is degenerate.
        return 0.0

    plus_di = (sum(plus_dm) / period) / atrv * 100.0
    minus_di = (sum(minus_dm) / period) / atrv * 100.0
    dx = abs(plus_di - minus_di) / max(plus_di + minus_di, 1e-9) * 100.0
    return dx  # This is an approximation of ADX for skeleton


def opening_range(bars: Sequence[Bar], n: int = 6) -> Tuple[float, float]:
    """Return (high, low) for the opening range; NaNs when the lookback is short."""

    if len(bars) < n:
        # Need ``n`` bars to form the opening range window.
        return (NAN, NAN)

    window = bars[:n]
    return (max(bar["h"] for bar in window), min(bar["l"] for bar in window))


def realized_vol(bars: Sequence[Bar], n: int = 12) -> float:
    """Compute a realized volatility estimate; NaN when the window is incomplete."""

    if len(bars) < n + 1:
        # Require the previous close plus ``n`` bars to form log returns.
        return NAN

    rsq = 0.0
    for i in range(1, n + 1):
        r = math.log(bars[i]["c"] / bars[i - 1]["c"])
        rsq += r * r

    # 5m bars per day ~288; rough annualization proxy
    return math.sqrt(rsq) * math.sqrt(288)


def band(value: float, cuts: Sequence[float], labels: Sequence[str]) -> str:
    """Return the first label with a threshold greater than the value, else the last."""

    for cutoff, label in zip(cuts, labels):
        if value <= cutoff:
            return label
    return labels[-1]
