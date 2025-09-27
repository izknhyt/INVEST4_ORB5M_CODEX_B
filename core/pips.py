"""
Pip utilities (skeleton): pip size and pip value helpers.

Assumptions:
- Symbols are like 'USDJPY', 'EURUSD' (BASEQUOTE, 6 chars or more).
- JPY crosses use pip size 0.01; others use 0.0001.
- pip_value(symbol, notional) returns value per pip in quote currency units
  for a position with `notional` units of base currency (simplified).
"""
from __future__ import annotations

def is_jpy_cross(symbol: str) -> bool:
    s = (symbol or "").upper()
    return s.endswith("JPY")

def pip_size(symbol: str) -> float:
    return 0.01 if is_jpy_cross(symbol) else 0.0001

def pips_to_price(pips: float, symbol: str) -> float:
    return float(pips) * pip_size(symbol)

def price_to_pips(price_move: float, symbol: str) -> float:
    ps = pip_size(symbol)
    return float(price_move) / ps if ps != 0 else 0.0

def pip_value(symbol: str, notional: float) -> float:
    """
    Return the quote-currency value per pip for a position size expressed in base currency units.
    Example: pip_value('EURUSD', 100000) -> 10.0 (USD per pip) in the classic convention.
    For 'USDJPY', pip_value('USDJPY', 100000) -> 1000.0 (JPY per pip) with this simplification.
    """
    return float(notional) * pip_size(symbol)

