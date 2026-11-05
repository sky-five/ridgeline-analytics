"""A seeded onboarding-funnel experiment with a planted true effect.

The story: new trial accounts are split 50/50 between the current onboarding (control) and a guided
setup checklist (treatment). The success metric is activation: the account sends its first proposal
within 14 days of signup. The checklist raises the true activation rate by a fixed amount, so the
analysis has a known answer to recover.

Every account goes through three steps (create a job, measure a roof, send a proposal); each step's
pass rate is set so the end-to-end rate equals the planted rate in each arm.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

SEED = 20261105
STEPS = ("created_job", "measured_roof", "sent_proposal")


@dataclass(frozen=True)
class Design:
    p_control: float = 0.30  # true 14-day activation rate without the checklist
    lift: float = 0.04  # planted true effect, absolute (30% -> 34%)
    days: int = 28  # length of the enrolment window
    arrivals_per_day: int = 170  # new trial accounts per day
    treatment_share: float = 0.5
    alpha: float = 0.05
    power: float = 0.8

    @property
    def p_treatment(self) -> float:
        return self.p_control + self.lift


def _step_rates(p_end: float, first_two: tuple[float, float]) -> tuple[float, float, float]:
    a, b = first_two
    return a, b, p_end / (a * b)


DEFAULT = Design()


def simulate(design: Design = DEFAULT, seed: int = SEED, lost_share: float = 0.0) -> pd.DataFrame:
    """One row per enrolled account: signup day, arm and which funnel steps it reached.

    `lost_share` is a tracking bug: the new onboarding fails to log that share of the treatment accounts
    that never activate (say, a tracking call that only fires once a user gets going). That both skews
    the split, which a sample-ratio-mismatch check exists to catch, and inflates the treatment's rate.
    """
    rng = np.random.default_rng(seed)
    n = design.days * design.arrivals_per_day
    day = np.repeat(np.arange(1, design.days + 1), design.arrivals_per_day)
    treated = rng.random(n) < design.treatment_share

    # the checklist mostly helps the middle step (measuring the first roof)
    control = _step_rates(design.p_control, (0.80, 0.625))
    treatment = _step_rates(design.p_treatment, (0.82, 0.70))
    rates = np.where(treated[:, None], np.array(treatment), np.array(control))
    passed = np.cumprod(rng.random((n, 3)) < rates, axis=1).astype(bool)

    df = pd.DataFrame({"account_id": np.arange(1, n + 1), "signup_day": day,
                       "arm": np.where(treated, "treatment", "control")})
    for i, step in enumerate(STEPS):
        df[step] = passed[:, i]
    df["activated"] = df["sent_proposal"]

    if lost_share:
        lost = treated & ~df["activated"].to_numpy() & (rng.random(n) < lost_share)
        df = df[~lost].reset_index(drop=True)
    return df


def daily_cumulative(df: pd.DataFrame) -> pd.DataFrame:
    """Running totals per arm at the end of each enrolment day, the data an analyst would see when peeking."""
    g = (df.groupby(["signup_day", "arm"])["activated"].agg(["size", "sum"]).unstack("arm").fillna(0)
         .cumsum())
    return pd.DataFrame({"day": g.index, "n_control": g[("size", "control")].astype(int).values,
                         "x_control": g[("sum", "control")].astype(int).values,
                         "n_treatment": g[("size", "treatment")].astype(int).values,
                         "x_treatment": g[("sum", "treatment")].astype(int).values})
