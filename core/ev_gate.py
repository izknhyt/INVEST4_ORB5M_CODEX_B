"""
EV Gate: Beta-Binomial (OCO) and t-lower (variable PnL) estimators
"""
from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Dict, Tuple, List, Optional

def beta_inv_cdf(alpha: float, beta: float, q: float) -> float:
    """Inverse CDF for the Beta distribution.

    Attempts to use ``scipy.stats.beta.ppf`` if SciPy is installed; otherwise
    falls back to a numerical bisection solver using the incomplete beta
    function.  The fallback implementation is adapted from the algorithm in
    *Numerical Recipes* and provides a reasonably accurate result for ``q`` in
    ``[0, 1]``.
    """
    try:  # SciPy provides a precise and fast implementation
        from scipy.stats import beta as scipy_beta  # type: ignore
        return float(scipy_beta.ppf(q, alpha, beta))
    except Exception:
        pass

    if q <= 0.0:
        return 0.0
    if q >= 1.0:
        return 1.0

    # Helper: continued fraction for incomplete beta
    def _betacf(a: float, b: float, x: float) -> float:
        MAXIT = 200
        EPS = 3e-8
        FPMIN = 1e-30
        m2 = 0
        aa = 0.0
        c = 1.0
        d = 1.0 - (a + b) * x / (a + 1.0)
        if abs(d) < FPMIN:
            d = FPMIN
        d = 1.0 / d
        h = d
        for m in range(1, MAXIT + 1):
            m2 = 2 * m
            aa = m * (b - m) * x / ((a + m2 - 1) * (a + m2))
            d = 1.0 + aa * d
            if abs(d) < FPMIN:
                d = FPMIN
            c = 1.0 + aa / c
            if abs(c) < FPMIN:
                c = FPMIN
            d = 1.0 / d
            h *= d * c
            aa = -(a + m) * (a + b + m) * x / ((a + m2) * (a + m2 + 1))
            d = 1.0 + aa * d
            if abs(d) < FPMIN:
                d = FPMIN
            c = 1.0 + aa / c
            if abs(c) < FPMIN:
                c = FPMIN
            d = 1.0 / d
            del_ = d * c
            h *= del_
            if abs(del_ - 1.0) < EPS:
                break
        return h

    def _betai(a: float, b: float, x: float) -> float:
        if x <= 0.0:
            return 0.0
        if x >= 1.0:
            return 1.0
        lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
        bt = math.exp(a * math.log(x) + b * math.log(1 - x) + lbeta)
        if x < (a + 1.0) / (a + b + 2.0):
            return bt * _betacf(a, b, x) / a
        return 1.0 - bt * _betacf(b, a, 1.0 - x) / b

    lo, hi = 0.0, 1.0
    for _ in range(100):
        mid = (lo + hi) / 2.0
        if _betai(alpha, beta, mid) < q:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0

@dataclass
class EwmaStats:
    mean: float = 0.0
    var: float = 0.0
    n_eff: float = 0.0
    decay: float = 0.02
    def update(self, x: float):
        a = self.decay
        self.n_eff = min(1e9, (1-a)*self.n_eff + 1.0)
        delta = x - self.mean
        self.mean += a * delta
        self.var = (1-a)*(self.var + a*delta*delta)

class BetaBinomialEV:
    def __init__(self, conf_level=0.95, decay=0.02, prior_alpha: float = 0.0, prior_beta: float = 0.0):
        self.alpha = 1.0
        self.beta = 1.0
        self.decay = decay
        self.conf_level = conf_level
        self.prior_alpha = max(0.0, float(prior_alpha))
        self.prior_beta = max(0.0, float(prior_beta))

    def update(self, hit: bool):
        a = self.decay
        # EWMA-like pseudo counts
        self.alpha = (1-a)*self.alpha + (1.0 if hit else 0.0)
        self.beta  = (1-a)*self.beta  + (0.0 if hit else 1.0)

    def update_weighted(self, w: float):
        """EWMA-like fractional update: w in [0,1] contributes to alpha, (1-w) to beta."""
        w = max(0.0, min(1.0, float(w)))
        a = self.decay
        self.alpha = (1-a)*self.alpha + w
        self.beta  = (1-a)*self.beta  + (1.0 - w)

    def p_lcb(self) -> float:
        a = self.prior_alpha + self.alpha
        b = self.prior_beta + self.beta
        # Lower confidence bound corresponds to the (1 - conf_level) quantile
        return beta_inv_cdf(a, b, 1.0 - self.conf_level)

    def p_mean(self) -> float:
        a = self.prior_alpha + self.alpha
        b = self.prior_beta + self.beta
        denom = a + b
        return (a/denom) if denom > 0 else 0.5

    def ev_lcb_oco(self, tp_pips: float, sl_pips: float, cost_pips: float) -> float:
        p = self.p_lcb()
        return p*tp_pips - (1-p)*sl_pips - cost_pips

class TLowerEV:
    def __init__(self, conf_level=0.95, decay=0.02):
        self.stats = EwmaStats(decay=decay)
        self.conf_level = conf_level

    def update(self, pnl_pips: float):
        self.stats.update(pnl_pips)

    def ev_lcb(self, cost_pips: float) -> float:
        # Student-t lower bound proxy using normal quantile (skeleton)
        z = 1.6448536269514722 if self.conf_level>=0.95 else 1.2815515655446004
        se = math.sqrt(max(self.stats.var, 1e-12) / max(self.stats.n_eff, 1.0))
        return (self.stats.mean - z*se) - cost_pips


class PooledEVManager:
    """Pooled EV wrapper that merges bucket, neighbor, and global pseudo-counts.
    - buckets: dict[key] -> BetaBinomialEV (created on demand)
    - key: current bucket key (e.g., (session, spread_band, rv_band))
    - neighbor_keys: optional neighbor keys for smoothing (e.g., rv_band adjacency)
    - lam_global: weight for global pool (0..1)
    - lam_neighbors: weight per neighbor (0..1)
    """
    def __init__(self,
                 buckets: Dict[Tuple, 'BetaBinomialEV'],
                 global_ev: 'BetaBinomialEV',
                 key: Tuple,
                 neighbor_keys: Optional[List[Tuple]] = None,
                 lam_global: float = 0.30,
                 lam_neighbors: float = 0.20):
        self.buckets = buckets
        self.global_ev = global_ev
        self.key = key
        self.neighbor_keys = neighbor_keys or []
        self.lam_global = lam_global
        self.lam_neighbors = lam_neighbors

        if key not in self.buckets:
            # inherit prior from global
            self.buckets[key] = BetaBinomialEV(conf_level=global_ev.conf_level,
                                               decay=global_ev.decay,
                                               prior_alpha=global_ev.prior_alpha,
                                               prior_beta=global_ev.prior_beta)
        for nk in self.neighbor_keys:
            if nk not in self.buckets:
                self.buckets[nk] = BetaBinomialEV(conf_level=global_ev.conf_level,
                                                  decay=global_ev.decay,
                                                  prior_alpha=global_ev.prior_alpha,
                                                  prior_beta=global_ev.prior_beta)

    def _pooled_counts(self) -> Tuple[float, float]:
        # Base counts: current bucket
        b = self.buckets[self.key]
        a_eff = b.prior_alpha + b.alpha
        b_eff = b.prior_beta + b.beta
        # Neighbors smoothing
        for nk in self.neighbor_keys:
            nb = self.buckets[nk]
            a_eff += self.lam_neighbors * (nb.prior_alpha + nb.alpha)
            b_eff += self.lam_neighbors * (nb.prior_beta + nb.beta)
        # Global pool
        ge = self.global_ev
        a_eff += self.lam_global * (ge.prior_alpha + ge.alpha)
        b_eff += self.lam_global * (ge.prior_beta + ge.beta)
        return a_eff, b_eff

    def p_lcb(self) -> float:
        a, b = self._pooled_counts()
        return beta_inv_cdf(a, b, self.global_ev.conf_level)

    def ev_lcb_oco(self, tp_pips: float, sl_pips: float, cost_pips: float) -> float:
        p = self.p_lcb()
        return p*tp_pips - (1.0-p)*sl_pips - cost_pips

    def update(self, hit: bool):
        # Update current bucket and global pool with the realized outcome
        self.buckets[self.key].update(hit)
        self.global_ev.update(hit)

    def update_weighted(self, w: float):
        self.buckets[self.key].update_weighted(w)
        self.global_ev.update_weighted(w)
