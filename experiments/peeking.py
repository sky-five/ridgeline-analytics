"""Why you should not stop an A/B test the first day it looks significant.

Simulates many A/A tests (both arms identical, so every "win" is a false positive) and compares two
analysts: one who tests once at the planned end, and one who tests after every day and stops at the
first p < alpha. The second one's false-positive rate is far above the 5% they think they have.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import NormalDist

import numpy as np

from experiments.simulate import DEFAULT, Design


@dataclass(frozen=True)
class PeekingResult:
    n_tests: int
    looks: int
    alpha: float
    false_positive_fixed: float  # one test at the planned end
    false_positive_peeking: float  # test daily, stop at the first significant look
    median_stop_day: float | None  # among peeking false positives

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def aa_tests(design: Design = DEFAULT, n_tests: int = 2000, seed: int = 7) -> PeekingResult:
    rng = np.random.default_rng(seed)
    per_arm = design.arrivals_per_day // 2
    shape = (n_tests, design.days)
    # same true rate in both arms; daily new accounts and activations per arm
    x_c = rng.binomial(per_arm, design.p_control, shape).cumsum(axis=1)
    x_t = rng.binomial(per_arm, design.p_control, shape).cumsum(axis=1)
    n = per_arm * np.arange(1, design.days + 1)

    pooled = (x_c + x_t) / (2 * n)
    se = np.sqrt(pooled * (1 - pooled) * 2 / n)
    z = np.divide(x_t / n - x_c / n, se, out=np.zeros(shape), where=se > 0)
    crit = NormalDist().inv_cdf(1 - design.alpha / 2)
    hit = np.abs(z) > crit

    fixed = float(hit[:, -1].mean())
    any_hit = hit.any(axis=1)
    first_day = hit.argmax(axis=1) + 1
    stop = float(np.median(first_day[any_hit])) if any_hit.any() else None
    return PeekingResult(n_tests, design.days, design.alpha, fixed, float(any_hit.mean()), stop)
