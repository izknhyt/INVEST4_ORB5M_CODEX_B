"""
Rule-based router v0 (5m): gates by session, spread band, RV band, OR quality, news freeze
"""
from __future__ import annotations
from typing import Dict

def pass_gates(ctx: Dict[str, any]) -> bool:
    if ctx.get("news_freeze"): return False
    if ctx.get("session") not in ("LDN","NY"): return False
    if ctx.get("spread_band") not in ("narrow","normal"): return False
    if ctx.get("allow_low_rv"):
        if ctx.get("rv_band") not in ("low","mid","high"): return False
    else:
        if ctx.get("rv_band") not in ("mid","high"): return False
    if ctx.get("or_atr_ratio", 0.0) < ctx.get("min_or_atr_ratio", 0.6): return False
    if ctx.get("expected_slip_pip", 0.0) > ctx.get("slip_cap_pip", 1.5): return False
    return True
