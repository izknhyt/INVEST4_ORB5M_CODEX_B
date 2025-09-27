"""
Fill engine (skeleton): Conservative and Bridge modes + Stop-Limit protection
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict

@dataclass
class OrderSpec:
    side: str          # BUY/SELL
    entry: float       # trigger/entry price
    tp_pips: float
    sl_pips: float
    trail_pips: float = 0.0
    slip_cap_pip: float = 1.5

class ConservativeFill:
    def simulate(self, bar: Dict[str,float], spec: OrderSpec) -> Dict[str,float]:
        # Assumes bar dict with keys: o,h,l,c, pip (pip size), spread
        pip = bar.get("pip", 0.01)
        entry = spec.entry
        # Stop-Limit: if breach beyond slip_cap, treat as cancel (no fill here)
        if spec.side == "BUY":
            if bar["h"] >= entry:
                worst_fill = entry + spec.slip_cap_pip * pip
                fill_px = min(bar["h"], worst_fill)
                # OCO conservative: SL hit first if both possible
                tp_px = entry + spec.tp_pips * pip
                sl_px = entry - spec.sl_pips * pip
                if bar["l"] <= sl_px and bar["h"] >= tp_px:
                    exit_px, reason = sl_px, "sl"  # worst-case first
                elif bar["l"] <= sl_px:
                    exit_px, reason = sl_px, "sl"
                elif bar["h"] >= tp_px:
                    exit_px, reason = tp_px, "tp"
                else:
                    return {"fill": True, "entry_px": fill_px, "exit": None}
                return {"fill": True, "entry_px": fill_px, "exit_px": exit_px, "exit_reason": reason}
        else:  # SELL
            if bar["l"] <= entry:
                worst_fill = entry - spec.slip_cap_pip * pip
                fill_px = max(bar["l"], worst_fill)
                tp_px = entry - spec.tp_pips * pip
                sl_px = entry + spec.sl_pips * pip
                if bar["h"] >= sl_px and bar["l"] <= tp_px:
                    exit_px, reason = sl_px, "sl"
                elif bar["h"] >= sl_px:
                    exit_px, reason = sl_px, "sl"
                elif bar["l"] <= tp_px:
                    exit_px, reason = tp_px, "tp"
                else:
                    return {"fill": True, "entry_px": fill_px, "exit": None}
                return {"fill": True, "entry_px": fill_px, "exit_px": exit_px, "exit_reason": reason}
        return {"fill": False}

class BridgeFill:
    def simulate(self, bar: Dict[str,float], spec: OrderSpec) -> Dict[str,float]:
        # Brownian-bridge inspired ordering probability between TP/SL when both are reachable in bar.
        pip = bar.get("pip", 0.01)
        entry = spec.entry
        ps = pip
        o,h,l,c = bar["o"], bar["h"], bar["l"], bar["c"]

        # Check trigger
        if spec.side == "BUY":
            if h < entry:
                return {"fill": False}
            worst_fill = entry + spec.slip_cap_pip * ps
            fill_px = min(h, worst_fill)
            tp_px = entry + spec.tp_pips * ps
            sl_px = entry - spec.sl_pips * ps
            # If only one reachable, deterministic
            if l <= sl_px and h < tp_px:
                return {"fill": True, "entry_px": fill_px, "exit_px": sl_px, "exit_reason": "sl", "p_tp": 0.0}
            if h >= tp_px and l > sl_px:
                return {"fill": True, "entry_px": fill_px, "exit_px": tp_px, "exit_reason": "tp", "p_tp": 1.0}
            # Neither reachable → carry over
            if not (l <= sl_px or h >= tp_px):
                return {"fill": True, "entry_px": fill_px, "exit": None}
            # Both reachable → estimate P(TP first)
            d_tp = max(spec.tp_pips, 1e-9)
            d_sl = max(spec.sl_pips, 1e-9)
            base = d_sl / (d_tp + d_sl)  # closer barrier more likely first
            rng = max(h - l, ps)
            drift = (c - o) / rng
            # BUY: positive drift favors TP
            import math
            drift_term = math.tanh(2.5 * drift)
            drift_prior = 0.5 * (1.0 + drift_term)
            lam = 0.35
            p_tp = min(0.999, max(0.001, (1 - lam) * base + lam * drift_prior))
            # Expected exit as mixture
            exp_exit = p_tp * tp_px + (1 - p_tp) * sl_px
            exit_reason = "tp" if p_tp >= 0.5 else "sl"
            return {"fill": True, "entry_px": fill_px, "exit_px": exp_exit, "exit_reason": exit_reason, "p_tp": p_tp}
        else:  # SELL
            if l > entry:
                return {"fill": False}
            worst_fill = entry - spec.slip_cap_pip * ps
            fill_px = max(l, worst_fill)
            tp_px = entry - spec.tp_pips * ps
            sl_px = entry + spec.sl_pips * ps
            if h >= sl_px and l > tp_px:
                return {"fill": True, "entry_px": fill_px, "exit_px": sl_px, "exit_reason": "sl", "p_tp": 0.0}
            if l <= tp_px and h < sl_px:
                return {"fill": True, "entry_px": fill_px, "exit_px": tp_px, "exit_reason": "tp", "p_tp": 1.0}
            if not (l <= tp_px or h >= sl_px):
                return {"fill": True, "entry_px": fill_px, "exit": None}
            d_tp = max(spec.tp_pips, 1e-9)
            d_sl = max(spec.sl_pips, 1e-9)
            base = d_sl / (d_tp + d_sl)
            rng = max(h - l, ps)
            drift = (o - c) / rng  # SELL: down move favors TP (lower)
            import math
            drift_term = math.tanh(2.5 * drift)
            drift_prior = 0.5 * (1.0 + drift_term)
            lam = 0.35
            p_tp = min(0.999, max(0.001, (1 - lam) * base + lam * drift_prior))
            exp_exit = p_tp * tp_px + (1 - p_tp) * sl_px
            exit_reason = "tp" if p_tp >= 0.5 else "sl"
            return {"fill": True, "entry_px": fill_px, "exit_px": exp_exit, "exit_reason": exit_reason, "p_tp": p_tp}
