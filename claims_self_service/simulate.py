"""A seeded, simulated book of property and casualty insurance: policies, the premium they earn and the
claims made against them, January 2025 to June 2026.

20,000 one-year policies start through 2025 across three lines of business (personal auto, homeowners,
small commercial property), four regions and three sales channels. Each policy files claims at a yearly
rate set by its line; each claim has a peril, a severity, a report lag and an outcome (approved, denied
or withdrawn) that is decided after a cycle time set by the line and peril. A claim whose decision falls
after the as-of date is still open and carries a case reserve as its incurred amount.

Two things are planted for the dashboard to find: a hailstorm in the south region in July 2025 that
files a burst of homeowners wind/hail claims, and the direct channel, whose claims are denied about twice
as often as the agent or broker channels' claims.
"""
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

SEED = 2025
FIRST_START = date(2025, 1, 1)
LAST_START = date(2025, 12, 31)
AS_OF = date(2026, 6, 30)
TERM_DAYS = 365
POLICIES = 20_000
REGIONS = ["north", "south", "east", "west"]
CHANNELS = {"agent": 0.50, "broker": 0.25, "direct": 0.25}
LINES = {
    # share of policies, median annual premium, claims per policy-year
    "personal_auto": (0.50, 1_400, 0.16),
    "homeowners": (0.35, 1_900, 0.07),
    "commercial_property": (0.15, 6_500, 0.12),
}
PERILS = {
    # peril_id: (line, peril group, chance within the line, median severity, mean cycle days)
    "auto_collision": ("personal_auto", "collision", 0.60, 4_200, 21),
    "auto_glass": ("personal_auto", "glass", 0.25, 650, 6),
    "auto_theft": ("personal_auto", "theft", 0.15, 9_500, 38),
    "home_water": ("homeowners", "water", 0.40, 7_800, 30),
    "home_wind_hail": ("homeowners", "wind_hail", 0.30, 11_000, 34),
    "home_fire": ("homeowners", "fire", 0.10, 38_000, 62),
    "home_theft": ("homeowners", "theft", 0.20, 3_600, 24),
    "cp_fire": ("commercial_property", "fire", 0.25, 45_000, 75),
    "cp_water": ("commercial_property", "water", 0.45, 14_000, 41),
    "cp_liability": ("commercial_property", "liability", 0.30, 22_000, 88),
}
SEVERITY_SIGMA = 0.9
REPORT_LAG_MEAN_DAYS = 6
DENY = {"agent": 0.09, "broker": 0.10, "direct": 0.20}
WITHDRAW = 0.04
OPEN_RESERVE = 1.15  # an open claim's case reserve, as a multiple of its eventual severity
OPEN_PAID_SHARE = 0.35  # share of an open claim's severity already paid
HAIL_REGION, HAIL_START, HAIL_DAYS = "south", date(2025, 7, 14), 6
HAIL_CLAIM_RATE = 0.22  # extra wind/hail claims per south homeowners policy in force during the storm


@dataclass
class Book:
    policies: pd.DataFrame
    perils: pd.DataFrame
    claims: pd.DataFrame


def _perils() -> pd.DataFrame:
    return pd.DataFrame(
        [(pid, line, group, mean_cycle) for pid, (line, group, _, _, mean_cycle) in PERILS.items()],
        columns=["peril_id", "line_of_business", "peril_group", "expected_cycle_days"],
    )


def _policies(rng: np.random.Generator) -> pd.DataFrame:
    lines = list(LINES)
    line = rng.choice(lines, POLICIES, p=[LINES[x][0] for x in lines])
    span = (LAST_START - FIRST_START).days + 1
    start = pd.to_datetime(FIRST_START) + pd.to_timedelta(rng.integers(0, span, POLICIES), unit="D")
    median = np.array([LINES[x][1] for x in line])
    premium = np.round(median * rng.lognormal(0, 0.35, POLICIES), 2)
    return pd.DataFrame({
        "policy_id": [f"P{i:05d}" for i in range(1, POLICIES + 1)],
        "line_of_business": line,
        "region": rng.choice(REGIONS, POLICIES),
        "channel": rng.choice(list(CHANNELS), POLICIES, p=list(CHANNELS.values())),
        "start_date": start.date,
        "end_date": (start + pd.Timedelta(days=TERM_DAYS - 1)).date,
        "annual_premium": premium,
    })


def _claim(rng, policy, peril_id: str, loss: date) -> dict | None:
    _, _, _, median_sev, mean_cycle = PERILS[peril_id]
    reported = loss + timedelta(days=int(rng.exponential(REPORT_LAG_MEAN_DAYS)))
    if reported > AS_OF:
        return None  # incurred but not reported: not in the claims system yet
    severity = round(median_sev * float(rng.lognormal(0, SEVERITY_SIGMA)), 2)
    u = rng.random()
    deny = DENY[policy.channel]
    outcome = "denied" if u < deny else "withdrawn" if u < deny + WITHDRAW else "approved"
    scale = 0.6 if outcome != "approved" else 1.0  # a denial or withdrawal is settled faster
    decided = reported + timedelta(days=1 + int(rng.gamma(2.0, mean_cycle * scale / 2.0)))
    row = {"policy_id": policy.policy_id, "peril_id": peril_id, "loss_date": loss, "reported_date": reported}
    if decided > AS_OF:
        return row | {"status": "open", "closed_date": None,
                      "incurred_amount": round(severity * OPEN_RESERVE, 2),
                      "paid_amount": round(severity * OPEN_PAID_SHARE, 2)}
    paid = severity if outcome == "approved" else 0.0
    return row | {"status": outcome, "closed_date": decided, "incurred_amount": paid, "paid_amount": paid}


def simulate(seed: int = SEED) -> Book:
    rng = np.random.default_rng(seed)
    policies = _policies(rng)
    perils_by_line = {
        line: ([p for p, v in PERILS.items() if v[0] == line], [v[2] for v in PERILS.values() if v[0] == line])
        for line in LINES
    }
    hail_end = HAIL_START + timedelta(days=HAIL_DAYS - 1)
    rows = []
    for pol in policies.itertuples(index=False):
        exposure_end = min(pol.end_date, AS_OF)
        exposure_days = (exposure_end - pol.start_date).days + 1
        n = rng.poisson(LINES[pol.line_of_business][2] * exposure_days / 365)
        ids, probs = perils_by_line[pol.line_of_business]
        for _ in range(n):
            loss = pol.start_date + timedelta(days=int(rng.integers(0, exposure_days)))
            rows.append(_claim(rng, pol, str(rng.choice(ids, p=probs)), loss))
        in_force = pol.start_date <= hail_end and pol.end_date >= HAIL_START
        if pol.line_of_business == "homeowners" and pol.region == HAIL_REGION and in_force:
            first = max(pol.start_date, HAIL_START)
            window = (min(pol.end_date, hail_end) - first).days + 1
            for _ in range(rng.poisson(HAIL_CLAIM_RATE)):
                loss = first + timedelta(days=int(rng.integers(0, window)))
                rows.append(_claim(rng, pol, "home_wind_hail", loss))
    claims = pd.DataFrame([r for r in rows if r is not None])
    claims = claims.sort_values(["reported_date", "policy_id", "loss_date"], kind="stable").reset_index(drop=True)
    claims.insert(0, "claim_id", [f"C{i:06d}" for i in range(1, len(claims) + 1)])
    for c in ("loss_date", "reported_date", "closed_date"):
        claims[c] = pd.to_datetime(claims[c])
    for c in ("start_date", "end_date"):
        policies[c] = pd.to_datetime(policies[c])
    return Book(policies=policies, perils=_perils(), claims=claims)
