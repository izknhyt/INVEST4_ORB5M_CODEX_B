"""
Position sizing: fractional Kelly (safe) + guard rails
"""
from __future__ import annotations
from dataclasses import dataclass

@dataclass
class SizingConfig:
    risk_per_trade_pct: float = 0.25
    kelly_fraction: float = 0.25
    units_cap: float = 5.0
    max_trade_loss_pct: float = 0.5

def base_units(equity: float, pip_value: float, sl_pips: float, cfg: SizingConfig) -> float:
    risk_amt = equity * (cfg.risk_per_trade_pct/100.0)
    return max(0.0, risk_amt / max(pip_value*sl_pips, 1e-9))

def kelly_multiplier_oco(p_lcb: float, tp_pips: float, sl_pips: float, cfg: SizingConfig) -> float:
    b = tp_pips / max(sl_pips, 1e-9)
    f_star = max(0.0, p_lcb - (1.0 - p_lcb)/b)
    return min(cfg.units_cap, cfg.kelly_fraction * f_star)

def apply_guards(units: float, equity: float, pip_value: float, sl_pips: float, cfg: SizingConfig) -> float:
    # Ensure 1-trade loss <= max_trade_loss_pct
    max_units = (equity * (cfg.max_trade_loss_pct/100.0)) / max(pip_value*sl_pips, 1e-9)
    return max(0.0, min(units, max_units, cfg.units_cap))
