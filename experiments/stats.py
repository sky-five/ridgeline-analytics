"""Two-proportion statistics for a conversion-rate A/B test, written out with the standard library.

Everything here is the textbook normal approximation, so each function can be checked by hand:

- sample_size_per_arm: accounts per arm to detect an absolute lift with the given power
- power: chance a test with n per arm detects a true lift
- two_proportion_test: pooled z-test p-value and an unpooled Wald confidence interval for the difference
- srm_test: chi-square check that the arms got the traffic split the design asked for
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from statistics import NormalDist

_N = NormalDist()


def _z(q: float) -> float:
    return _N.inv_cdf(q)


def sample_size_per_arm(p_control: float, lift: float, alpha: float = 0.05, power: float = 0.8) -> int:
    """Accounts needed in each arm for a two-sided test to detect `lift` (absolute) with `power`."""
    if not 0 < p_control < 1 or not 0 < p_control + lift < 1 or lift == 0:
        raise ValueError("rates must be between 0 and 1 and the lift non-zero")
    p_t = p_control + lift
    z = _z(1 - alpha / 2) + _z(power)
    return math.ceil(z**2 * (p_control * (1 - p_control) + p_t * (1 - p_t)) / lift**2)


def power(p_control: float, lift: float, n_per_arm: int, alpha: float = 0.05) -> float:
    """Probability that a two-sided test with `n_per_arm` per arm comes out significant when the lift is real."""
    p_t = p_control + lift
    se = math.sqrt((p_control * (1 - p_control) + p_t * (1 - p_t)) / n_per_arm)
    return _N.cdf(abs(lift) / se - _z(1 - alpha / 2))


@dataclass(frozen=True)
class TestResult:
    n_control: int
    n_treatment: int
    rate_control: float
    rate_treatment: float
    diff: float  # treatment minus control, absolute
    relative_lift: float
    z: float
    p_value: float
    ci_low: float
    ci_high: float
    significant: bool

    def as_dict(self) -> dict:
        return asdict(self)


def two_proportion_test(x_c: int, n_c: int, x_t: int, n_t: int, alpha: float = 0.05) -> TestResult:
    """Pooled two-sided z-test of treatment vs control, and a (1 - alpha) Wald interval for the difference."""
    if min(n_c, n_t) <= 0:
        raise ValueError("both arms need at least one account")
    p_c, p_t = x_c / n_c, x_t / n_t
    diff = p_t - p_c
    pooled = (x_c + x_t) / (n_c + n_t)
    se_pooled = math.sqrt(pooled * (1 - pooled) * (1 / n_c + 1 / n_t))
    z = diff / se_pooled if se_pooled > 0 else 0.0
    p_value = 2 * (1 - _N.cdf(abs(z)))
    se = math.sqrt(p_c * (1 - p_c) / n_c + p_t * (1 - p_t) / n_t)
    half = _z(1 - alpha / 2) * se
    return TestResult(n_c, n_t, p_c, p_t, diff, diff / p_c if p_c else math.nan, z, p_value,
                      diff - half, diff + half, p_value < alpha)


def srm_test(n_c: int, n_t: int, treatment_share: float = 0.5) -> tuple[float, float]:
    """Sample-ratio-mismatch check: chi-square statistic (1 df) and its p-value for the observed split.

    A tiny p-value (the usual alarm is below 0.001) means assignment or logging is broken, and the
    lift estimate should not be trusted until that is fixed.
    """
    total = n_c + n_t
    expected = (total * (1 - treatment_share), total * treatment_share)
    chi2 = sum((o - e) ** 2 / e for o, e in zip((n_c, n_t), expected, strict=True))
    # chi-square with 1 df is a squared standard normal
    return chi2, 2 * (1 - _N.cdf(math.sqrt(chi2)))
