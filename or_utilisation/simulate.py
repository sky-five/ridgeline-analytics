"""A seeded, simulated surgical suite: 12 operating rooms, 26 weeks of weekday block time, January to June 2026.

Each room-day is one 8-hour block (07:30 to 15:30) owned by a surgical service on a fixed weekly template.
On a normal day the owning service books cases into its block. Some days the surgeon is away: the block has
no cases of its own. If the absence is known in time the service may release the block, and another service
on the waitlist may pick it up. Same-day cancellations leave gaps that are not refilled; they are more common
in January and February (the winter months), so utilisation rises in the spring on its own.

From 2026-04-06 an auto-release rule runs: a block with nothing booked 72 hours ahead is released
automatically unless the surgeon overrides it. That rule is the thing whose return is being claimed.

Every random draw for a block comes from that block's own generator, so the same half-year can be replayed
with the rule switched off. The replay (`Suite.truth`) is the planted truth for the rule's real effect; it
is never loaded into the warehouse.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

import numpy as np
import pandas as pd

SEED = 2026
FIRST_DAY = date(2026, 1, 5)
WEEKS = 26
POLICY_START = date(2026, 4, 6)  # week 14
ROOMS = [f"OR-{i:02d}" for i in range(1, 13)]
BLOCK_START = time(7, 30)
BLOCK_MINUTES = 480
TURNOVER_MINUTES = 30
SERVICES = {
    # mean booked minutes per case, chance the surgeon is away on a block day
    "general_surgery": (95, 0.14),
    "orthopaedics": (130, 0.16),
    "urology": (70, 0.12),
    "gynaecology": (85, 0.13),
    "ent": (60, 0.15),
    "plastics": (110, 0.18),
}
KNOWN_AHEAD = 0.80  # absences known at least 72 h before the block
VOLUNTARY_RELEASE = 0.35  # services release a known absence on their own this often
AUTO_RELEASE_HOURS = 72
OVERRIDE = 0.08  # under the rule, the surgeon keeps the block this often
PICKUP_GOOD_NOTICE = 0.65  # a block released 72 h+ ahead finds a taker
PICKUP_SHORT_NOTICE = 0.25
OWN_FILL = 1.00  # services book up to this share of the block, turnovers included
PICKUP_FILL = 0.80
CANCEL_BY_MONTH = {1: 0.11, 2: 0.10, 3: 0.08, 4: 0.06, 5: 0.06, 6: 0.06, 7: 0.06}


@dataclass
class Suite:
    services: pd.DataFrame
    blocks: pd.DataFrame
    releases: pd.DataFrame
    cases: pd.DataFrame
    truth: dict = field(default_factory=dict)  # the rule's effect from the replay (never loaded)


def block_days() -> list[date]:
    days = [FIRST_DAY + timedelta(d) for d in range(WEEKS * 7)]
    return [d for d in days if d.weekday() < 5]


def owner(room_index: int, weekday: int) -> str:
    """Fixed weekly template: each service gets 10 of the 60 room-days a week."""
    names = list(SERVICES)
    return names[(room_index + 2 * weekday) % len(names)]


def _book(rng: np.random.Generator, mean: float, fill: float) -> list[int]:
    """Booked minutes per case, added while the case and the turnovers before it fit in fill x the block."""
    booked, used = [], 0
    while True:
        minutes = int(max(20, round(rng.lognormal(np.log(mean), 0.35) / 5) * 5))
        need = minutes + (TURNOVER_MINUTES if booked else 0)
        if booked and used + need > fill * BLOCK_MINUTES:
            return booked
        booked.append(min(minutes, BLOCK_MINUTES))
        used += need


def _run_cases(rng: np.random.Generator, block_id: str, day: date, room: str, service: str,
               booked: list[int], cancel_rate: float) -> list[dict]:
    """Cases run back to back from the block start; a same-day cancellation is not refilled."""
    rows, clock = [], datetime.combine(day, BLOCK_START)
    for k, minutes in enumerate(booked):
        cancelled = rng.random() < cancel_rate
        actual = int(round(minutes * rng.lognormal(0, 0.12)))
        row = {"case_id": f"{block_id}-{service[:3]}-{k + 1}", "block_id": block_id, "room_id": room,
               "case_date": day, "service_id": service, "booked_minutes": minutes,
               "status": "cancelled" if cancelled else "completed", "wheels_in": None, "wheels_out": None}
        if not cancelled:
            if any(r["status"] == "completed" for r in rows):
                clock += timedelta(minutes=TURNOVER_MINUTES)
            row["wheels_in"] = clock
            clock += timedelta(minutes=actual)
            row["wheels_out"] = clock
        rows.append(row)
    return rows


def simulate(policy: bool = True, replay: bool = True) -> Suite:
    """The half-year with the auto-release rule from POLICY_START (policy=True) or never (policy=False).
    With replay=True the other world is also run and the rule's true effect stored in `truth`."""
    blocks, releases, cases = [], [], []
    names = list(SERVICES)
    for di, day in enumerate(block_days()):
        cancel_rate = CANCEL_BY_MONTH[day.month]
        for ri, room in enumerate(ROOMS):
            block_id = f"{day:%Y%m%d}-{room}"
            service = owner(ri, day.weekday())
            mean, p_away = SERVICES[service]
            rng = np.random.default_rng([SEED, di, ri])
            u_away, u_known, u_notice, u_release, u_pickup, u_taker = rng.random(6)
            start = datetime.combine(day, BLOCK_START)
            blocks.append({"block_id": block_id, "block_date": day, "room_id": room, "service_id": service,
                           "starts_at": start, "ends_at": start + timedelta(minutes=BLOCK_MINUTES)})
            if u_away >= p_away:
                booked = _book(np.random.default_rng([SEED, di, ri, 1]), mean, OWN_FILL)
                cases += _run_cases(np.random.default_rng([SEED, di, ri, 2]), block_id, day, room, service,
                                    booked, cancel_rate)
                continue
            known_hours = 72 + u_notice * 264 if u_known < KNOWN_AHEAD else 4 + u_notice * 67
            notice, kind = None, None
            if u_release < VOLUNTARY_RELEASE:
                notice, kind = known_hours, "voluntary"
            elif policy and day >= POLICY_START and known_hours >= AUTO_RELEASE_HOURS \
                    and u_release < 1 - OVERRIDE:
                notice, kind = AUTO_RELEASE_HOURS, "auto"
            if notice is None:
                continue
            releases.append({"block_id": block_id, "released_at": start - timedelta(hours=round(notice)),
                             "release_type": kind})
            if u_pickup < (PICKUP_GOOD_NOTICE if notice >= AUTO_RELEASE_HOURS else PICKUP_SHORT_NOTICE):
                taker = [s for s in names if s != service][int(u_taker * (len(names) - 1))]
                booked = _book(np.random.default_rng([SEED, di, ri, 3]), SERVICES[taker][0], PICKUP_FILL)
                cases += _run_cases(np.random.default_rng([SEED, di, ri, 4]), block_id, day, room, taker,
                                    booked, cancel_rate)
    suite = Suite(
        services=pd.DataFrame({"service_id": names, "mean_booked_minutes": [SERVICES[s][0] for s in names]}),
        blocks=pd.DataFrame(blocks),
        releases=pd.DataFrame(releases, columns=["block_id", "released_at", "release_type"]),
        cases=pd.DataFrame(cases),
    )
    if replay:
        other = simulate(policy=not policy, replay=False)
        with_rule, without = (suite, other) if policy else (other, suite)
        suite.truth = {
            "in_block_minutes_with_rule": _post_minutes(with_rule),
            "in_block_minutes_without_rule": _post_minutes(without),
            "added_in_block_minutes": _post_minutes(with_rule) - _post_minutes(without),
            "added_completed_cases": _post_cases(with_rule) - _post_cases(without),
        }
    return suite


def _post(s: Suite) -> pd.DataFrame:
    c = s.cases
    return c[(c["status"] == "completed") & (pd.to_datetime(c["case_date"]) >= pd.Timestamp(POLICY_START))]


def _post_minutes(s: Suite) -> int:
    """Completed minutes inside the block window (15:30 at the latest), as the marts count them."""
    c = _post(s)
    end = pd.to_datetime(c["case_date"]) + pd.Timedelta(minutes=7 * 60 + 30 + BLOCK_MINUTES)
    return int(((c["wheels_out"].clip(upper=end) - c["wheels_in"]).dt.total_seconds() // 60).clip(lower=0).sum())


def _post_cases(s: Suite) -> int:
    return len(_post(s))
