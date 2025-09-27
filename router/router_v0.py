"""
Rule-based router v0 (5m): gates by session, spread band, RV band, OR quality, news freeze
"""
from __future__ import annotations
from typing import Dict

def pass_gates(ctx: Dict[str, any]) -> bool:
    if ctx.get("news_freeze"):
        return False

    allowed_sessions = ctx.get("allowed_sessions")
    if allowed_sessions and ctx.get("session") not in allowed_sessions:
        return False

    if ctx.get("spread_band") not in ("narrow", "normal"):
        return False

    return True
