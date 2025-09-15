import math
import pytest
from core.ev_gate import beta_inv_cdf, BetaBinomialEV


def wilson_beta_inv_cdf(alpha: float, beta: float, q: float) -> float:
    n = alpha + beta
    if n <= 0:
        return 0.0
    p_hat = alpha / n
    z = 1.6448536269514722 if q >= 0.95 else 1.2815515655446004
    denom = 1 + z*z/n
    centre = p_hat + z*z/(2*n)
    adj = z*math.sqrt((p_hat*(1-p_hat)+z*z/(4*n))/n)
    return max(0.0, (centre - adj)/denom)


def test_beta_inv_cdf_uniform():
    assert beta_inv_cdf(1.0, 1.0, 0.25) == pytest.approx(0.25, abs=1e-9)


def test_beta_inv_cdf_differs_from_wilson():
    new_val = beta_inv_cdf(5.0, 7.0, 0.05)
    old_val = wilson_beta_inv_cdf(5.0, 7.0, 0.95)
    assert abs(new_val - old_val) > 1e-2


def test_betabinomialev_p_lcb():
    bb = BetaBinomialEV(conf_level=0.95, decay=0.1)
    for hit in [True, False, True, True, False, True, True]:
        bb.update(hit)
    p = bb.p_lcb()
    mean = bb.p_mean()
    assert 0.0 <= p <= mean <= 1.0
