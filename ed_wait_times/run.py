"""Write the results: results/summary.json (last week's breaches, how often each site breached, the public ICU
file's profile and the odd days its data test found) and results/site_week.csv. Every number comes from the dbt
marts."""
import json
from pathlib import Path

import duckdb
import pandas as pd

from ed_wait_times import public
from ed_wait_times.breaches import breaches
from ed_wait_times.simulate import CLOSURE_SITE, CLOSURE_START, FIRST_DAY, LAST_DAY

RESULTS = Path(__file__).resolve().parent / "results"
SUMMARY = RESULTS / "summary.json"
SITE_WEEK = RESULTS / "site_week.csv"


def _round(x, digits=4):
    return round(float(x), digits)


def summary(db: Path) -> dict:
    with duckdb.connect(str(db), read_only=True) as con:
        last = breaches(con)
        weeks = con.sql("""
            select site_id, count(*) as weeks, count(*) filter (where breached) as breached_weeks,
                   count(*) filter (where not reportable) as unreported_weeks,
                   median(p90_los_hours) as median_weekly_p90_hours, avg(mean_bed_occupancy) as mean_bed_occupancy
            from site_week where patient_group = 'admitted' group by 1 order by 1""").df()
        closure = con.execute("""
            select week_start >= ? as after, count(*) as weeks, count(*) filter (where breached) as breached_weeks,
                   median(p90_los_hours) as median_p90, avg(mean_bed_occupancy) as occupancy
            from site_week where patient_group = 'admitted' and site_id = ? group by 1 order by 1""",
                              [CLOSURE_START, CLOSURE_SITE]).df()
        totals = con.sql("""select count(*) as visits, count(*) filter (where patient_group = 'admitted') as admitted,
                            quantile_cont(los_hours, 0.9) filter (where patient_group = 'admitted') as p90_admitted
                            from stg_ed__visits""").fetchone()
        icu = con.sql("""select min(census_date), max(census_date), count(*), avg(adult_occupancy_rate),
                         quantile_cont(adult_occupancy_rate, 0.5) from icu_province_day""").fetchone()
        odd = con.sql("""select census_date, total_adult_icu_patients, total_adult_icu_beds, total_ped_icu_patients,
                         total_ped_icu_beds, over_capacity, adult_patients_outlier
                         from icu_province_day where over_capacity or adult_patients_outlier
                         order by census_date""").df()
    return {
        "simulated": {
            "first_day": FIRST_DAY.isoformat(), "last_day": LAST_DAY.isoformat(), "sites": len(weeks),
            "visits": int(totals[0]), "admitted": int(totals[1]), "p90_admitted_hours_all": _round(totals[2], 2),
        },
        "last_week": last,
        "admitted_weeks_by_site": [
            {"site_id": r.site_id, "weeks": int(r.weeks), "breached_weeks": int(r.breached_weeks),
             "unreported_weeks": int(r.unreported_weeks),
             "median_weekly_p90_hours": _round(r.median_weekly_p90_hours, 2),
             "mean_bed_occupancy": _round(r.mean_bed_occupancy)}
            for r in weeks.itertuples()
        ],
        "bed_closure": {
            "site_id": CLOSURE_SITE, "from": CLOSURE_START.isoformat(),
            **{("after" if r.after else "before"): {"weeks": int(r.weeks), "breached_weeks": int(r.breached_weeks),
                                                     "median_p90_hours": _round(r.median_p90, 2),
                                                     "mean_bed_occupancy": _round(r.occupancy)}
               for r in closure.itertuples()},
        },
        "public_icu": {
            "source": public.DATASET, "licence": public.LICENCE, "sha256": public.SHA256,
            "first_day": str(icu[0]), "last_day": str(icu[1]), "days": int(icu[2]),
            "mean_adult_occupancy": _round(icu[3]), "median_adult_occupancy": _round(icu[4]),
            "odd_days": [
                {"date": pd.Timestamp(r.census_date).date().isoformat(),
                 "adult_patients": int(r.total_adult_icu_patients),
                 "adult_beds": int(r.total_adult_icu_beds),
                 "ped_patients": int(r.total_ped_icu_patients),
                 "ped_beds": int(r.total_ped_icu_beds),
                 "over_capacity": bool(r.over_capacity),
                 "adult_patients_outlier": bool(r.adult_patients_outlier)}
                for r in odd.itertuples()
            ],
        },
    }


def site_week_csv(db: Path) -> str:
    with duckdb.connect(str(db), read_only=True) as con:
        df = con.sql("select * from site_week order by site_id, week_start, patient_group").df()
    df = df.round({"p90_los_hours": 3, "share_within_target": 4, "mean_bed_occupancy": 4})
    df["week_start"] = pd.to_datetime(df["week_start"]).dt.date
    return df.to_csv(index=False, lineterminator="\n")


def to_json(s: dict) -> str:
    return json.dumps(s, indent=2, default=str) + "\n"
