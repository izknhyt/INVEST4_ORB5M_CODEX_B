"""
Feature Store (5m mode) — minimal calculations for ATR, ADX, OR width, RV, bands
NOTE: Placeholder computations; replace with vetted implementations during integration.
"""
from __future__ import annotations

import math
from typing import Mapping, Optional, Sequence, Tuple


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


def realized_vol(bars: Optional[Sequence[Bar]], n: int = 12) -> float:
    """Compute realized volatility for the most recent ``n`` returns."""

    if not bars or len(bars) < n + 1:
        # Require the previous close plus ``n`` bars to form log returns.
        return NAN

    if len(bars) != n + 1:
        window = list(bars)[-(n + 1) :]
    else:
        window = bars

    rsq = 0.0
    for i in range(1, n + 1):
        prev_close = window[i - 1]["c"]
        curr_close = window[i]["c"]
        r = math.log(curr_close / prev_close)
        rsq += r * r

    # 5m bars per day ~288; rough annualization proxy
    return math.sqrt(rsq) * math.sqrt(288)


def band(value: float, cuts: Sequence[float], labels: Sequence[str]) -> str:
    """Return the first label with a threshold greater than the value, else the last."""

    for cutoff, label in zip(cuts, labels):
        if value <= cutoff:
            return label
    return labels[-1]


def _to_float(value: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _last_closes(bars: Sequence[Bar], window: int) -> Sequence[float]:
    if window <= 0:
        return []
    if len(bars) < window:
        return []
    closes: list[float] = []
    for bar in bars[-window:]:
        closes.append(_to_float(bar.get("c", 0.0)))
    return closes


def _correlation(values: Sequence[float]) -> float:
    n = len(values)
    if n < 3:
        return 0.0
    mean_x = (n - 1) / 2.0
    mean_y = sum(values) / n
    cov = 0.0
    var_x = 0.0
    var_y = 0.0
    for idx, val in enumerate(values):
        dx = idx - mean_x
        dy = val - mean_y
        cov += dx * dy
        var_x += dx * dx
        var_y += dy * dy
    if var_x <= 0.0 or var_y <= 0.0:
        return 0.0
    corr = cov / math.sqrt(var_x * var_y)
    if corr != corr:
        return 0.0
    return max(-1.0, min(1.0, corr))


def micro_zscore(bars: Sequence[Bar], window: int = 12) -> float:
    """Return the short-window z-score of the most recent close."""

    closes = _last_closes(bars, window)
    if len(closes) < window:
        return 0.0
    mean = sum(closes) / window
    var = sum((val - mean) ** 2 for val in closes) / window
    std = math.sqrt(var)
    if std <= 1e-9:
        return 0.0
    z = (closes[-1] - mean) / std
    if z != z or not math.isfinite(z):
        return 0.0
    return max(-6.0, min(6.0, z))


def micro_trend(bars: Sequence[Bar], window: int = 10) -> float:
    """Return the correlation between price and time over a short window."""

    closes = _last_closes(bars, window)
    if len(closes) < window:
        return 0.0
    return _correlation(closes)


def mid_price(bar: Mapping[str, float]) -> float:
    """Return the bar mid price using ``(high + low) / 2``."""

    high = _to_float(bar.get("h", 0.0))
    low = _to_float(bar.get("l", 0.0))
    return (high + low) / 2.0


def trend_score(bars: Sequence[Bar], window: int = 36) -> float:
    """Compute a bounded trend score using range positioning and correlation."""

    closes = _last_closes(bars, window)
    if len(closes) < window:
        return 0.0
    hi = max(closes)
    lo = min(closes)
    rng = hi - lo
    if rng <= 0.0:
        return 0.0
    corr = _correlation(closes)
    position = (closes[-1] - lo) / rng
    directional = (position - 0.5) * 2.0
    score = directional * abs(corr)
    if score != score or not math.isfinite(score):
        return 0.0
    return max(-1.0, min(1.0, score))


def pullback(bars: Sequence[Bar], window: int = 20) -> float:
    """Return the normalized pullback from recent extremes (0 = none, 1 = deep)."""

    if not bars:
        return 0.0
    lookback = bars[-window:] if len(bars) >= window else bars
    highs: list[float] = []
    lows: list[float] = []
    for bar in lookback:
        highs.append(_to_float(bar.get("h", 0.0)))
        lows.append(_to_float(bar.get("l", 0.0)))
    hi = max(highs)
    lo = min(lows)
    rng = hi - lo
    if rng <= 0.0:
        return 0.0
    close = _to_float(lookback[-1].get("c", 0.0))
    distance_high = max(0.0, hi - close)
    distance_low = max(0.0, close - lo)
    depth = min(distance_high, distance_low) / rng
    if depth != depth or not math.isfinite(depth):
        return 0.0
    return max(0.0, min(1.0, depth))
