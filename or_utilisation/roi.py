"""The return on the auto-release rule, three ways, against the replayed truth.

- claimed: the change in adjusted block utilisation times all block hours. Every check in validate.py that
  can fire on it does.
- before/after: the change in room utilisation times all block hours. Honest numerator and denominator, but
  it credits the spring drop in cancellations and any change in how many surgeons were away.
- defended: the rule can only add cases in released blocks. So count the minutes other services had patients
  in released time after the rule started, minus what the before-period reuse per block minute would have
  given on the same block minutes. A day-level bootstrap gives the 95% interval.

The simulator replays the same half-year with the rule off; the difference in in-block patient minutes is
the truth. Money: an assumed contribution margin per patient hour and an assumed cost for the rule. Both are
placeholders a finance team would replace; the minutes are what the analysis stands behind.
"""
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

MARGIN_PER_HOUR_USD = 1_500  # assumed contribution margin per patient hour in the room
RULE_COST_USD = 25_000  # assumed cost of running the rule for the 13 weeks (scheduler time, set-up)
BOOTSTRAP = 2_000
SEED = 7


@dataclass
class Estimate:
    added_minutes: float
    ci_low: float | None
    ci_high: float | None
    net_usd: float


@dataclass
class Roi:
    claimed: Estimate
    before_after: Estimate
    defended: Estimate
    true_added_minutes: int
    true_net_usd: float
    defended_ci_covers_truth: bool
    claimed_over_truth: float


def net_usd(minutes: float) -> float:
    return round(minutes / 60 * MARGIN_PER_HOUR_USD - RULE_COST_USD)


def defended_minutes(daily: pd.DataFrame) -> float:
    """daily: one row per block day with period, allocated_minutes, reused_in_block_minutes."""
    s = daily.groupby("period")[["allocated_minutes", "reused_in_block_minutes"]].sum()
    baseline = s.loc["before", "reused_in_block_minutes"] / s.loc["before", "allocated_minutes"]
    return float(s.loc["after", "reused_in_block_minutes"] - baseline * s.loc["after", "allocated_minutes"])


def _bootstrap(daily: pd.DataFrame) -> tuple[float, float]:
    rng = np.random.default_rng(SEED)
    parts = {p: daily[daily["period"] == p][["allocated_minutes", "reused_in_block_minutes"]].to_numpy()
             for p in ("before", "after")}
    sums = {}
    for p, a in parts.items():
        idx = rng.integers(0, len(a), size=(BOOTSTRAP, len(a)))
        sums[p] = a[idx].sum(axis=1)  # (BOOTSTRAP, 2)
    est = sums["after"][:, 1] - sums["before"][:, 1] / sums["before"][:, 0] * sums["after"][:, 0]
    lo, hi = np.percentile(est, [2.5, 97.5])
    return float(lo), float(hi)


def roi(by_period: pd.DataFrame, daily: pd.DataFrame, truth: dict) -> Roi:
    rows = by_period.set_index(["period", "blocks_in_scope"])
    before, after = rows.loc[("before", "all")], rows.loc[("after", "all")]
    minutes = float(after["allocated_minutes"])
    claimed = (after["adjusted_block_utilisation"] - before["adjusted_block_utilisation"]) * minutes
    before_after = (after["room_utilisation"] - before["room_utilisation"]) * minutes
    defended = defended_minutes(daily)
    lo, hi = _bootstrap(daily)
    true = int(truth["added_in_block_minutes"])
    return Roi(
        claimed=Estimate(round(claimed), None, None, net_usd(claimed)),
        before_after=Estimate(round(before_after), None, None, net_usd(before_after)),
        defended=Estimate(round(defended), round(lo), round(hi), net_usd(defended)),
        true_added_minutes=true,
        true_net_usd=net_usd(true),
        defended_ci_covers_truth=lo <= true <= hi,
        claimed_over_truth=round(claimed / true, 1),
    )


def to_dict(r: Roi) -> dict:
    return asdict(r)
