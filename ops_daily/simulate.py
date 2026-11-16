"""A seeded, simulated claims operation: three sites (east, central, west), two lines (home, auto).

Two feeds, as the systems would deliver them:

- `calls`: one row per site, line and day from the phone system, 2026-01-01 to 2026-06-30: calls offered,
  answered, abandoned, answered within 60 seconds, total handle seconds (talk, hold and wrap) and staffed hours;
- `claims`: one row per claim from the claims system, with the day it was opened and the day it was closed (empty
  while still open on the as-of date). Claims start in 2025-11 so the backlog on 2026-01-01 is already settled.

Volumes follow the weekday (Monday busiest, Sunday quietest). Each day's staffing is planned for the expected
volume at 78% occupancy, and covers 70% of any surprise on the day; when the real load runs above that, fewer
calls are answered within 60 seconds and more callers hang up. A claim can close from its third day, first in
first out, up to the day's closing capacity.

Planted for the flag rule to find (EVENTS):

- west auto loses staff from 2026-06-22: staffed hours drop to 82% of plan, service level falls, abandons rise;
- east home handle time creeps up from 2026-06-08, by 18% over two weeks (a new verification step), and stays;
- a windstorm hits central home on 2026-06-18: new claims and calls jump, then fade over about a week, and the
  claims backlog builds because closing capacity does not change.
"""
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

SEED = 520
CLAIMS_FROM = date(2025, 11, 3)  # claims are simulated from here so the backlog is settled by 2026-01-01
FIRST_DAY, AS_OF = date(2026, 1, 1), date(2026, 6, 30)

SITES = {"east": 1.0, "central": 1.4, "west": 0.8}  # volume factor
# line -> (calls a weekday at factor 1, handle seconds per call, claims opened a weekday at factor 1)
LINES = {"home": (260, 540, 22), "auto": (340, 450, 30)}
CALL_WEEKDAY = [1.25, 1.10, 1.00, 1.00, 0.95, 0.45, 0.25]  # Monday .. Sunday
CLAIM_WEEKDAY = [1.30, 1.10, 1.00, 1.00, 0.95, 0.30, 0.15]
CLOSE_WEEKDAY = [1.0, 1.0, 1.0, 1.0, 1.0, 0.3, 0.0]  # adjusters work weekdays, a few on Saturday
CLOSE_HEADROOM = 1.12  # weekday closing capacity over the average weekday's new claims
MIN_DAYS_OPEN = 2  # a claim can close from opened + 2 days
TARGET_OCCUPANCY = 0.78
SERVICE_SECONDS = 60

STAFF_CUT = ("west", "auto", date(2026, 6, 22), 0.82)  # site, line, from, staffed hours as a share of plan
HANDLE_CREEP = ("east", "home", date(2026, 6, 8), 14, 0.18)  # site, line, from, days to ramp, increase
STORM = ("central", "home", date(2026, 6, 18), 4.0, 1.5, 3.0)  # site, line, day, claims x, calls x, decay days
EVENTS = [  # what the flag rule should find: (name, site, line, from, the metric the cause shows up in)
    ("staff_cut", STAFF_CUT[0], STAFF_CUT[1], STAFF_CUT[2], "service_level"),
    ("handle_time_creep", HANDLE_CREEP[0], HANDLE_CREEP[1], HANDLE_CREEP[2], "avg_handle_minutes"),
    ("storm", STORM[0], STORM[1], STORM[2], "claims_opened"),
]


@dataclass
class Operation:
    calls: pd.DataFrame
    claims: pd.DataFrame


def _days(start: date, end: date) -> list[date]:
    return [d.date() for d in pd.date_range(start, end, freq="D")]


def handle_factor(site: str, line: str, day: date) -> float:
    s, ln, start, ramp, up = HANDLE_CREEP
    if (site, line) != (s, ln) or day < start:
        return 1.0
    return 1.0 + up * min(1.0, ((day - start).days + 1) / ramp)


def staff_factor(site: str, line: str, day: date) -> float:
    s, ln, start, share = STAFF_CUT
    return share if (site, line) == (s, ln) and day >= start else 1.0


def storm_factor(site: str, line: str, day: date, which: str) -> float:
    s, ln, start, claims_x, calls_x, decay = STORM
    if (site, line) != (s, ln) or day < start:
        return 1.0
    return 1.0 + (claims_x if which == "claims" else calls_x) * np.exp(-(day - start).days / decay)


def service_level(occupancy: float) -> float:
    """Share of calls answered within 60 seconds at a given occupancy, before noise."""
    return float(np.clip(0.92 - 1.5 * max(0.0, occupancy - 0.72), 0.05, 0.98))


def abandon_rate(occupancy: float) -> float:
    return float(np.clip(0.025 + 0.8 * max(0.0, occupancy - 0.80), 0.0, 0.5))


def _calls(rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    for day in _days(FIRST_DAY, AS_OF):
        wd = CALL_WEEKDAY[day.weekday()]
        for site, sf in SITES.items():
            for line, (calls, aht, _) in LINES.items():
                expected = calls * sf * wd
                offered = int(rng.poisson(expected * storm_factor(site, line, day, "calls")))
                handle = aht * handle_factor(site, line, day) * rng.normal(1, 0.02)
                # planned for the expected volume, 70% of any surprise covered on the day (overtime, breaks moved)
                planned = expected * aht / 3600 / TARGET_OCCUPANCY * (0.3 + 0.7 * offered / expected)
                staffed = planned * rng.normal(1, 0.02) * staff_factor(site, line, day)
                occ = offered * handle / 3600 / staffed
                abandoned = int(round(offered * max(0.0, abandon_rate(occ) + rng.normal(0, 0.004))))
                answered = offered - abandoned
                within = min(answered, int(round(offered * float(np.clip(service_level(occ) + rng.normal(0, 0.015),
                                                                         0, 1)))))
                rows.append({"call_date": day, "site": site, "line": line, "offered": offered,
                             "answered": answered, "abandoned": abandoned, "answered_within_60s": within,
                             "handle_seconds": int(round(answered * handle)), "staffed_hours": round(staffed, 1)})
    return pd.DataFrame(rows)


def _claims(rng: np.random.Generator) -> pd.DataFrame:
    rows, n = [], 0
    days = _days(CLAIMS_FROM, AS_OF)
    for site, sf in SITES.items():
        for line, (_, _, claims) in LINES.items():
            weekday_mean = claims * sf * np.mean(CLAIM_WEEKDAY) * 7 / 5
            queue: list[dict] = []
            for day in days:
                new = int(rng.poisson(claims * sf * CLAIM_WEEKDAY[day.weekday()]
                                      * storm_factor(site, line, day, "claims")))
                for _ in range(new):
                    n += 1
                    c = {"claim_id": f"CL{n:06d}", "site": site, "line": line, "opened_date": day,
                         "closed_date": None}
                    rows.append(c)
                    queue.append(c)
                capacity = int(rng.poisson(weekday_mean * CLOSE_HEADROOM * CLOSE_WEEKDAY[day.weekday()]))
                ready = [c for c in queue if (day - c["opened_date"]).days >= MIN_DAYS_OPEN][:capacity]
                for c in ready:
                    c["closed_date"] = day
                queue = [c for c in queue if c["closed_date"] is None]
    df = pd.DataFrame(rows)
    df["closed_date"] = pd.to_datetime(df["closed_date"]).dt.date
    return df


def simulate(seed: int = SEED) -> Operation:
    rng = np.random.default_rng(seed)
    return Operation(calls=_calls(rng), claims=_claims(rng))
