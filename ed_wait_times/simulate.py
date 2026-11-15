"""A seeded, simulated emergency-department visit log and midnight bed census for ten hospital sites, every day
from 2026-01-05 to 2026-11-08 (44 full weeks, Monday to Sunday).

Ontario publishes how long patients spend in emergency departments only as a monthly figure per hospital in an
online viewer, not as a downloadable per-site, per-day file, so the per-site data here is simulated. It follows
the public definitions: time in the ED runs from triage to leaving, admitted patients have an 8-hour target,
high-urgency patients sent home (triage levels 1 to 3) have 8 hours, low-urgency patients sent home (levels 4
and 5) have 4 hours, and each is reported as the 90th percentile.

Admitted patients wait in the ED for a ward bed, so their time in the ED grows when the hospital is full. Three
things are planted:

- the teaching site ED03 runs above 98% of its staffed beds, so its admitted patients breach 8 hours most weeks;
- ED07 closes 24 staffed beds from 2026-10-26: it is fine before and breaches after;
- the small site ED10 admits about 2 patients a day, so most weeks it has fewer than the 20 patients needed to
  report a 90th percentile.
"""
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

SEED = 816
FIRST_DAY = date(2026, 1, 5)  # a Monday
LAST_DAY = date(2026, 11, 8)  # a Sunday: the last full week is 2026-11-02 to 2026-11-08
CLOSURE_SITE, CLOSURE_START, CLOSED_BEDS = "ED07", date(2026, 10, 26), 24
CHRONIC_SITE = "ED03"
SMALL_SITE = "ED10"
WEEKDAY = np.array([1.12, 1.02, 0.98, 0.97, 0.99, 0.95, 0.97])  # Monday is the busiest day in the ED
LOW_URGENCY_TRIAGE = (4, 5)


@dataclass(frozen=True)
class Site:
    site_type: str
    region: str
    visits: float  # mean arrivals a day
    admit: float  # share of visits admitted
    beds: int  # staffed inpatient beds
    occupancy: float  # mean midnight occupancy of staffed beds
    care_hours: float  # median hours from triage to a decision, before any wait for a bed


SITES = {
    "ED01": Site("teaching", "Toronto", 260, 0.17, 620, 0.93, 3.4),
    "ED02": Site("teaching", "East", 210, 0.16, 480, 0.91, 3.3),
    "ED03": Site("teaching", "Central", 240, 0.18, 540, 0.985, 3.5),
    "ED04": Site("large community", "West", 180, 0.13, 330, 0.92, 3.1),
    "ED05": Site("large community", "Central", 170, 0.12, 300, 0.90, 3.0),
    "ED06": Site("large community", "Toronto", 190, 0.14, 350, 0.93, 3.2),
    "ED07": Site("large community", "East", 150, 0.12, 260, 0.90, 3.0),
    "ED08": Site("small community", "North", 70, 0.09, 90, 0.86, 2.6),
    "ED09": Site("small community", "West", 60, 0.08, 75, 0.85, 2.5),
    "ED10": Site("small community", "North", 30, 0.07, 40, 0.83, 2.4),
}


@dataclass(frozen=True)
class World:
    visits: pd.DataFrame  # one row per ED visit
    census: pd.DataFrame  # one row per site and day: staffed and occupied inpatient beds at midnight


def days() -> pd.DatetimeIndex:
    return pd.date_range(FIRST_DAY, LAST_DAY, freq="D")


def _season(d: pd.DatetimeIndex) -> np.ndarray:
    """Busier in winter (respiratory season), quieter in late summer."""
    return 1 + 0.08 * np.cos(2 * np.pi * (d.dayofyear.to_numpy() - 15) / 365)


def staffed_beds(site_id: str, d: pd.DatetimeIndex) -> np.ndarray:
    beds = np.full(len(d), SITES[site_id].beds)
    if site_id == CLOSURE_SITE:
        beds[d >= pd.Timestamp(CLOSURE_START)] -= CLOSED_BEDS
    return beds


def _boarding_hours(rng: np.random.Generator, occupancy: np.ndarray) -> np.ndarray:
    """Hours an admitted patient waits for a ward bed: short with beds free, long when the wards are full."""
    pressure = np.clip(occupancy - 0.90, 0, None)
    return rng.exponential(0.5 + 40 * pressure**1.2)


def simulate(seed: int = SEED) -> World:
    rng = np.random.default_rng(seed)
    d = days()
    visits, census = [], []
    for site_id, s in SITES.items():
        beds = staffed_beds(site_id, d)
        # occupied beds: the site's usual load (in beds) with winter pressure and day-to-day noise; when beds
        # close, the same patients sit in fewer beds
        load = s.occupancy * s.beds * (1 + 0.04 * (_season(d) - 1) / 0.08) * rng.normal(1, 0.015, len(d))
        occupied = np.minimum(np.round(load), np.round(beds * 1.05)).astype(int)
        census.append(pd.DataFrame({"site_id": site_id, "census_date": d.date, "staffed_beds": beds,
                                    "occupied_beds": occupied}))
        occ = occupied / beds

        n = rng.poisson(s.visits * WEEKDAY[d.dayofweek.to_numpy()] * _season(d))
        day_idx = np.repeat(np.arange(len(d)), n)
        total = len(day_idx)
        triage = rng.choice([1, 2, 3, 4, 5], total, p=[0.01, 0.17, 0.46, 0.27, 0.09])
        # admission is far likelier for urgent patients; scale so the site's overall share is about s.admit
        weight = np.array([0, 0.85, 0.40, 0.16, 0.04, 0.01])[triage]
        admitted = rng.random(total) < weight * s.admit / 0.17
        care = s.care_hours * rng.lognormal(0, 0.40, total) * np.where(triage >= 4, 0.55, 1.0)
        los = care + np.where(admitted, _boarding_hours(rng, occ[day_idx]), 0)
        arrived = (pd.to_datetime(d.date[day_idx]) + pd.to_timedelta(np.floor(rng.uniform(0, 24 * 60, total)), "min"))
        visits.append(pd.DataFrame({
            "site_id": site_id,
            "triage_at": arrived,
            "triage_level": triage,
            "disposition": np.where(admitted, "admitted", "discharged"),
            "left_ed_at": arrived + pd.to_timedelta((los * 60).round(), "min"),
        }))
    v = pd.concat(visits, ignore_index=True).sort_values(["triage_at", "site_id"], kind="stable")
    v.insert(0, "visit_id", np.arange(1, len(v) + 1))
    return World(visits=v.reset_index(drop=True), census=pd.concat(census, ignore_index=True))


def site_frame() -> pd.DataFrame:
    return pd.DataFrame([{"site_id": k, "site_type": s.site_type, "region": s.region} for k, s in SITES.items()])


def last_full_week() -> tuple[date, date]:
    return LAST_DAY - timedelta(days=6), LAST_DAY
