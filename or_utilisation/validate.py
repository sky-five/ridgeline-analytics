"""Check a before/after utilisation claim for framings that make a number move without more surgery.

A claim is "metric M went from X before the auto-release rule to Y after it". Each check looks at one way
that change can mislead, using only warehouse numbers and the flags in metric_spec.yml:

- denominator_moved: the metric's denominator changed between the periods (adjusted block utilisation drops
  released time, so releasing more raises it with no extra case). Sized as the part of the change left
  after putting the before-period denominator back.
- counts_turnover: cleaning and set-up time counted as used time. Sized as its points on top of the plain rate.
- misses_the_gain: the numerator leaves out the minutes the rule can add (another service's cases in released
  time), so whatever it shows is not the rule's doing.
- moved_where_rule_cannot_act: the same metric moved on blocks the owning service booked. The rule acts only
  on blocks with nothing booked, so that move (fewer winter cancellations here) is not the rule; a plain
  before/after credits it anyway.
- unequal_windows: the periods differ in days or weekday mix.
"""
from collections import Counter
from dataclasses import asdict, dataclass

import pandas as pd

from or_utilisation import spec

CLAIMED = ["adjusted_block_utilisation", "block_utilisation_with_turnover", "block_utilisation", "room_utilisation"]
DENOMINATOR_TOLERANCE = 0.02  # relative change per day
UNTOUCHED_TOLERANCE_PP = 1.0


@dataclass
class Check:
    check: str
    flagged: bool
    size_pp: float | None
    detail: str


@dataclass
class ClaimReview:
    metric: str
    before: float
    after: float
    change_pp: float
    checks: list[Check]

    @property
    def flags(self) -> list[str]:
        return [c.check for c in self.checks if c.flagged]


def _pp(x: float) -> float:
    return round(100 * x, 2)


def review(metric: str, by_period: pd.DataFrame, days: dict[str, list] | None = None) -> ClaimReview:
    """by_period: the utilisation_by_period mart. days: block dates per period, for the window check."""
    rows = by_period.set_index(["period", "blocks_in_scope"])
    before, after = rows.loc[("before", "all")], rows.loc[("after", "all")]
    m = spec.metrics()[metric]
    v0, v1 = spec.value(metric, before), spec.value(metric, after)
    checks = []

    d0 = spec.denominator(metric, before) / before["days"]
    d1 = spec.denominator(metric, after) / after["days"]
    moved = abs(d1 / d0 - 1)
    same_denominator = spec.numerator(metric, after) / spec.denominator(metric, before) * after["days"] / before["days"]
    checks.append(Check(
        "denominator_moved", bool(moved > DENOMINATOR_TOLERANCE), _pp(v1 - same_denominator),
        f"denominator per day {d0:,.0f} -> {d1:,.0f} minutes ({d1 / d0 - 1:+.1%}); with the before denominator "
        f"the change is {_pp(same_denominator - v0):+.1f} pp, not {_pp(v1 - v0):+.1f} pp"))

    if m["includes_turnover"]:
        plain = m["numerator"].replace(" + owner_turnover_minutes", "")
        extra = float(after["owner_turnover_minutes"]) / spec.denominator(metric, after)
        checks.append(Check("counts_turnover", True, _pp(extra),
                            f"turnover adds {_pp(extra):.1f} pp to the after-period rate; without it: {plain}"))
    else:
        checks.append(Check("counts_turnover", False, 0.0, "turnover is not counted as used time"))

    misses = "reused_in_block_minutes" not in m["numerator"]
    checks.append(Check(
        "misses_the_gain", misses, None,
        "counts only the owning service's minutes; the rule adds minutes for other services in released blocks"
        if misses else "counts every patient minute in the block window, released blocks included"))

    b0, b1 = rows.loc[("before", "owner_booked")], rows.loc[("after", "owner_booked")]
    untouched = spec.value(metric, b1) - spec.value(metric, b0)
    checks.append(Check(
        "moved_where_rule_cannot_act", bool(abs(_pp(untouched)) >= UNTOUCHED_TOLERANCE_PP), _pp(untouched),
        f"on blocks the owner booked (the rule cannot act there) it moved {_pp(untouched):+.1f} pp; "
        f"same-day cancellations {b0['same_day_cancellation_rate']:.1%} -> {b1['same_day_cancellation_rate']:.1%}"))

    if days is not None:
        mix = {p: Counter(pd.Timestamp(d).day_name() for d in ds) for p, ds in days.items()}
        unequal = mix["before"] != mix["after"]
        checks.append(Check("unequal_windows", unequal, None,
                            f"{len(days['before'])} vs {len(days['after'])} block days, weekday mix "
                            f"{'differs' if unequal else 'the same'}"))
    return ClaimReview(metric, round(v0, 4), round(v1, 4), _pp(v1 - v0), checks)


def to_dict(r: ClaimReview) -> dict:
    return {**asdict(r), "flags": r.flags}
