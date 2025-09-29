"""Fill engine utilities for Conservative / Bridge fills with broker policies."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional, Tuple


class SameBarPolicy(str, Enum):
    """How to resolve TP/SL hits inside the same bar."""

    SL_FIRST = "sl_first"
    TP_FIRST = "tp_first"
    PROBABILISTIC = "probabilistic"


@dataclass
class OrderSpec:
    side: str  # BUY/SELL
    entry: float  # trigger/entry price
    tp_pips: float
    sl_pips: float
    trail_pips: float = 0.0
    slip_cap_pip: float = 1.5
    same_bar_policy: Optional[SameBarPolicy] = None


class _BaseFill:
    """Common helpers shared by Conservative / Bridge fill models."""

    def __init__(
        self,
        default_policy: SameBarPolicy,
        lam: float = 0.35,
        drift_scale: float = 2.5,
    ) -> None:
        self.default_policy = default_policy
        self.lam = lam
        self.drift_scale = drift_scale

    def _policy(self, spec: OrderSpec) -> SameBarPolicy:
        return spec.same_bar_policy or self.default_policy

    def _bridge_probability(
        self,
        side: str,
        entry: float,
        tp_px: float,
        stop_px: float,
        bar: Dict[str, float],
        pip: float,
    ) -> float:
        d_tp = max(abs(tp_px - entry) / max(pip, 1e-9), 1e-9)
        d_sl = max(abs(entry - stop_px) / max(pip, 1e-9), 1e-9)
        base = d_sl / (d_tp + d_sl)
        rng = max(bar["h"] - bar["l"], pip)
        if rng <= 0:
            rng = pip
        if side == "BUY":
            drift = (bar["c"] - bar["o"]) / rng
        else:
            drift = (bar["o"] - bar["c"]) / rng
        drift_term = math.tanh(self.drift_scale * drift)
        drift_prior = 0.5 * (1.0 + drift_term)
        return min(0.999, max(0.001, (1 - self.lam) * base + self.lam * drift_prior))

    @staticmethod
    def _eval_trailing(
        side: str,
        entry: float,
        sl_px: float,
        trail_pips: float,
        bar: Dict[str, float],
        pip: float,
    ) -> Tuple[bool, Optional[float]]:
        if trail_pips <= 0:
            return False, None
        if side == "BUY":
            trigger_price = entry + trail_pips * pip
            if bar["h"] >= trigger_price:
                trail_px = max(sl_px, bar["h"] - trail_pips * pip)
                if bar["l"] <= trail_px:
                    return True, trail_px
                return False, trail_px
            return False, None
        trigger_price = entry - trail_pips * pip
        if bar["l"] <= trigger_price:
            trail_px = min(sl_px, bar["l"] + trail_pips * pip)
            if bar["h"] >= trail_px:
                return True, trail_px
            return False, trail_px
        return False, None

    def _resolve_same_bar(
        self,
        spec: OrderSpec,
        tp_px: float,
        stop_info: Tuple[float, str],
        bar: Dict[str, float],
        pip: float,
        include_prob: bool,
    ) -> Tuple[float, str, Optional[float]]:
        policy = self._policy(spec)
        if policy == SameBarPolicy.TP_FIRST:
            p_tp = 1.0 if include_prob else None
            return tp_px, "tp", p_tp
        if policy == SameBarPolicy.SL_FIRST:
            p_tp = 0.0 if include_prob else None
            return stop_info[0], stop_info[1], p_tp
        p_tp = self._bridge_probability(spec.side, spec.entry, tp_px, stop_info[0], bar, pip)
        exit_px = p_tp * tp_px + (1 - p_tp) * stop_info[0]
        exit_reason = "tp" if p_tp >= 0.5 else stop_info[1]
        return exit_px, exit_reason, p_tp


class ConservativeFill(_BaseFill):
    def __init__(self, same_bar_policy: SameBarPolicy = SameBarPolicy.SL_FIRST) -> None:
        super().__init__(same_bar_policy)

    def simulate(self, bar: Dict[str, float], spec: OrderSpec) -> Dict[str, float]:
        pip = bar.get("pip", 0.01) or 0.01
        entry = spec.entry
        if spec.side == "BUY":
            if bar["h"] < entry:
                return {"fill": False}
            worst_fill = entry + spec.slip_cap_pip * pip
            fill_px = min(bar["h"], worst_fill)
            tp_px = entry + spec.tp_pips * pip
            sl_px = entry - spec.sl_pips * pip
            trail_hit, trail_px = self._eval_trailing("BUY", entry, sl_px, spec.trail_pips, bar, pip)
            stop_hit = False
            stop_info: Optional[Tuple[float, str]] = None
            if trail_hit:
                stop_hit = True
                stop_info = (trail_px or sl_px, "trail")
            elif bar["l"] <= sl_px:
                stop_hit = True
                stop_info = (sl_px, "sl")
            tp_hit = bar["h"] >= tp_px
            if stop_hit and tp_hit:
                exit_px, exit_reason, p_tp = self._resolve_same_bar(
                    spec, tp_px, stop_info, bar, pip, include_prob=False
                )
                result = {
                    "fill": True,
                    "entry_px": fill_px,
                    "exit_px": exit_px,
                    "exit_reason": exit_reason,
                }
                if p_tp is not None:
                    result["p_tp"] = p_tp
                return result
            if stop_hit:
                return {
                    "fill": True,
                    "entry_px": fill_px,
                    "exit_px": stop_info[0],
                    "exit_reason": stop_info[1],
                }
            if tp_hit:
                return {
                    "fill": True,
                    "entry_px": fill_px,
                    "exit_px": tp_px,
                    "exit_reason": "tp",
                }
            result = {"fill": True, "entry_px": fill_px, "exit": None}
            if trail_px is not None and not trail_hit:
                result["trail_stop_px"] = trail_px
            return result

        if bar["l"] > entry:
            return {"fill": False}
        worst_fill = entry - spec.slip_cap_pip * pip
        fill_px = max(bar["l"], worst_fill)
        tp_px = entry - spec.tp_pips * pip
        sl_px = entry + spec.sl_pips * pip
        trail_hit, trail_px = self._eval_trailing("SELL", entry, sl_px, spec.trail_pips, bar, pip)
        stop_hit = False
        stop_info = None
        if trail_hit:
            stop_hit = True
            stop_info = (trail_px or sl_px, "trail")
        elif bar["h"] >= sl_px:
            stop_hit = True
            stop_info = (sl_px, "sl")
        tp_hit = bar["l"] <= tp_px
        if stop_hit and tp_hit:
            exit_px, exit_reason, p_tp = self._resolve_same_bar(spec, tp_px, stop_info, bar, pip, include_prob=False)
            result = {
                "fill": True,
                "entry_px": fill_px,
                "exit_px": exit_px,
                "exit_reason": exit_reason,
            }
            if p_tp is not None:
                result["p_tp"] = p_tp
            return result
        if stop_hit:
            return {
                "fill": True,
                "entry_px": fill_px,
                "exit_px": stop_info[0],
                "exit_reason": stop_info[1],
            }
        if tp_hit:
            return {
                "fill": True,
                "entry_px": fill_px,
                "exit_px": tp_px,
                "exit_reason": "tp",
            }
        result = {"fill": True, "entry_px": fill_px, "exit": None}
        if trail_px is not None and not trail_hit:
            result["trail_stop_px"] = trail_px
        return result


class BridgeFill(_BaseFill):
    def __init__(
        self,
        same_bar_policy: SameBarPolicy = SameBarPolicy.PROBABILISTIC,
        lam: float = 0.35,
        drift_scale: float = 2.5,
    ) -> None:
        super().__init__(same_bar_policy, lam=lam, drift_scale=drift_scale)

    def simulate(self, bar: Dict[str, float], spec: OrderSpec) -> Dict[str, float]:
        pip = bar.get("pip", 0.01) or 0.01
        entry = spec.entry
        if spec.side == "BUY":
            if bar["h"] < entry:
                return {"fill": False}
            worst_fill = entry + spec.slip_cap_pip * pip
            fill_px = min(bar["h"], worst_fill)
            tp_px = entry + spec.tp_pips * pip
            sl_px = entry - spec.sl_pips * pip
            trail_hit, trail_px = self._eval_trailing("BUY", entry, sl_px, spec.trail_pips, bar, pip)
            stop_hit = False
            stop_info: Optional[Tuple[float, str]] = None
            if trail_hit:
                stop_hit = True
                stop_info = (trail_px or sl_px, "trail")
            elif bar["l"] <= sl_px:
                stop_hit = True
                stop_info = (sl_px, "sl")
            tp_hit = bar["h"] >= tp_px
            if stop_hit and tp_hit:
                exit_px, exit_reason, p_tp = self._resolve_same_bar(spec, tp_px, stop_info, bar, pip, include_prob=True)
                return {
                    "fill": True,
                    "entry_px": fill_px,
                    "exit_px": exit_px,
                    "exit_reason": exit_reason,
                    "p_tp": p_tp,
                }
            if stop_hit:
                p_tp = 0.0
                if stop_info[1] == "trail" and self._policy(spec) == SameBarPolicy.PROBABILISTIC:
                    # Trailing stop can still exit with some locked profit; treat as certainty of stop
                    p_tp = 0.0
                return {
                    "fill": True,
                    "entry_px": fill_px,
                    "exit_px": stop_info[0],
                    "exit_reason": stop_info[1],
                    "p_tp": p_tp,
                }
            if tp_hit:
                return {
                    "fill": True,
                    "entry_px": fill_px,
                    "exit_px": tp_px,
                    "exit_reason": "tp",
                    "p_tp": 1.0,
                }
            result = {"fill": True, "entry_px": fill_px, "exit": None}
            if trail_px is not None and not trail_hit:
                result["trail_stop_px"] = trail_px
            return result

        if bar["l"] > entry:
            return {"fill": False}
        worst_fill = entry - spec.slip_cap_pip * pip
        fill_px = max(bar["l"], worst_fill)
        tp_px = entry - spec.tp_pips * pip
        sl_px = entry + spec.sl_pips * pip
        trail_hit, trail_px = self._eval_trailing("SELL", entry, sl_px, spec.trail_pips, bar, pip)
        stop_hit = False
        stop_info = None
        if trail_hit:
            stop_hit = True
            stop_info = (trail_px or sl_px, "trail")
        elif bar["h"] >= sl_px:
            stop_hit = True
            stop_info = (sl_px, "sl")
        tp_hit = bar["l"] <= tp_px
        if stop_hit and tp_hit:
            exit_px, exit_reason, p_tp = self._resolve_same_bar(spec, tp_px, stop_info, bar, pip, include_prob=True)
            return {
                "fill": True,
                "entry_px": fill_px,
                "exit_px": exit_px,
                "exit_reason": exit_reason,
                "p_tp": p_tp,
            }
        if stop_hit:
            return {
                "fill": True,
                "entry_px": fill_px,
                "exit_px": stop_info[0],
                "exit_reason": stop_info[1],
                "p_tp": 0.0,
            }
        if tp_hit:
            return {
                "fill": True,
                "entry_px": fill_px,
                "exit_px": tp_px,
                "exit_reason": "tp",
                "p_tp": 1.0,
            }
        result = {"fill": True, "entry_px": fill_px, "exit": None}
        if trail_px is not None and not trail_hit:
            result["trail_stop_px"] = trail_px
        return result
