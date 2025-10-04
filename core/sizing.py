"""
Position sizing: fractional Kelly (safe) + guard rails
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping, Optional


@dataclass
class SizingConfig:
    risk_per_trade_pct: float = 0.25
    kelly_fraction: float = 0.25
    units_cap: float = 5.0
    max_trade_loss_pct: float = 0.5


def base_units(equity: float, pip_value: float, sl_pips: float, cfg: SizingConfig) -> float:
    risk_amt = equity * (cfg.risk_per_trade_pct / 100.0)
    return max(0.0, risk_amt / max(pip_value * sl_pips, 1e-9))


def kelly_multiplier_oco(p_lcb: float, tp_pips: float, sl_pips: float, cfg: SizingConfig) -> float:
    b = tp_pips / max(sl_pips, 1e-9)
    f_star = max(0.0, p_lcb - (1.0 - p_lcb) / b)
    return min(cfg.units_cap, cfg.kelly_fraction * f_star)


def apply_guards(units: float, equity: float, pip_value: float, sl_pips: float, cfg: SizingConfig) -> float:
    # Ensure 1-trade loss <= max_trade_loss_pct
    max_units = (equity * (cfg.max_trade_loss_pct / 100.0)) / max(pip_value * sl_pips, 1e-9)
    return max(0.0, min(units, max_units, cfg.units_cap))


def _extract_sizing_config(ctx: Mapping[str, Any]) -> SizingConfig:
    cfg = SizingConfig()
    data = ctx.get("sizing_cfg")
    if isinstance(data, Mapping):
        risk_pct = data.get("risk_per_trade_pct")
        if risk_pct is not None:
            try:
                cfg.risk_per_trade_pct = float(risk_pct)
            except (TypeError, ValueError):
                pass
        kelly_fraction = data.get("kelly_fraction")
        if kelly_fraction is not None:
            try:
                cfg.kelly_fraction = float(kelly_fraction)
            except (TypeError, ValueError):
                pass
        units_cap = data.get("units_cap")
        if units_cap is not None:
            try:
                cfg.units_cap = float(units_cap)
            except (TypeError, ValueError):
                pass
        max_trade_loss_pct = data.get("max_trade_loss_pct")
        if max_trade_loss_pct is not None:
            try:
                cfg.max_trade_loss_pct = float(max_trade_loss_pct)
            except (TypeError, ValueError):
                pass
    return cfg


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def compute_qty_from_ctx(
    ctx: Mapping[str, Any],
    sl_pips: float,
    *,
    mode: Literal["calibration", "warmup", "production"],
    tp_pips: Optional[float] = None,
    p_lcb: Optional[float] = None,
    multiplier: Optional[float] = None,
) -> float:
    """Derive guarded position size using ``ctx`` sizing configuration.

    Parameters
    ----------
    ctx:
        Strategy/runner context containing equity, pip value, and sizing_cfg.
    sl_pips:
        Stop-loss distance in pips for the signal.
    mode:
        Controls how quantity is derived:
        - ``"calibration"`` returns the unit qty (or size floor when EV is disabled).
        - ``"warmup"`` applies the warmup multiplier from ``ctx``.
        - ``"production"`` applies Kelly sizing using ``p_lcb`` and ``tp_pips``.
    tp_pips / p_lcb:
        Required when ``mode == "production"`` to derive Kelly multiplier.
    multiplier:
        Optional explicit multiplier override (for warmup/calibration floor).
    """

    cfg = _extract_sizing_config(ctx)
    equity = _to_float(ctx.get("equity"))
    pip_value = _to_float(ctx.get("pip_value"))
    sl_val = _to_float(sl_pips)
    base = base_units(equity, pip_value, sl_val, cfg)

    if mode == "calibration":
        if str(ctx.get("ev_mode")) == "off":
            mult = multiplier if multiplier is not None else _to_float(ctx.get("size_floor_mult"), 0.01)
            return apply_guards(base * max(0.0, mult), equity, pip_value, sl_val, cfg)
        return 1.0

    if mode == "warmup":
        mult = multiplier if multiplier is not None else _to_float(ctx.get("warmup_mult"), 0.05)
        return apply_guards(base * max(0.0, mult), equity, pip_value, sl_val, cfg)

    if mode == "production":
        tp_val = _to_float(tp_pips)
        p_val = _to_float(p_lcb)
        mult = kelly_multiplier_oco(p_val, tp_val, sl_val, cfg)
        return apply_guards(base * mult, equity, pip_value, sl_val, cfg)

    raise ValueError(f"Unsupported sizing mode: {mode}")
