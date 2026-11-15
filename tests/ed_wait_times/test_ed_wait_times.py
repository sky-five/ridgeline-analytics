"""Checks the warehouse built once in conftest.py (simulate + load + dbt build, about 10 s): the dbt numbers against
an independent pandas count from the raw visits, the planted patterns, the breach query on a hand-made week, the
public ICU file as published, and the committed results."""
from datetime import date

import duckdb
import numpy as np
import pandas as pd
import pytest

from ed_wait_times import public
from ed_wait_times.breaches import breaches, last_full_week
from ed_wait_times.run import SITE_WEEK, SUMMARY, site_week_csv, summary, to_json
from ed_wait_times.simulate import (
    CHRONIC_SITE,
    CLOSED_BEDS,
    CLOSURE_SITE,
    CLOSURE_START,
    FIRST_DAY,
    LAST_DAY,
    SITES,
    SMALL_SITE,
    simulate,
)


@pytest.fixture(scope="module")
def con(db):
    with duckdb.connect(str(db), read_only=True) as c:
        yield c


def _df(con, sql: str) -> pd.DataFrame:
    """Query result with date columns as datetime.date, the way the raw-visit counts below key them."""
    df = con.sql(sql).df()
    for col in ("week_start", "day", "census_date"):
        if col in df:
            df[col] = pd.to_datetime(df[col]).dt.date
    return df


@pytest.fixture(scope="module")
def admitted_weeks(world) -> pd.DataFrame:
    """Weekly 90th percentile hours for admitted patients, computed straight from the raw visits."""
    v = world.visits[world.visits["disposition"] == "admitted"].copy()
    v["hours"] = (v["left_ed_at"] - v["triage_at"]).dt.total_seconds() / 3600
    v["week_start"] = v["triage_at"].dt.to_period("W-SUN").dt.start_time.dt.date
    return v.groupby(["site_id", "week_start"])["hours"].agg(
        p90=lambda h: np.quantile(h, 0.9), n="size", within=lambda h: (h <= 8).mean()).reset_index()


def test_simulation_is_seeded_and_covers_every_site_and_day(world):
    again = simulate()
    pd.testing.assert_frame_equal(world.visits, again.visits)
    assert world.visits["triage_at"].min().date() == FIRST_DAY
    assert world.visits["triage_at"].max().date() == LAST_DAY
    assert len(world.census) == len(SITES) * ((LAST_DAY - FIRST_DAY).days + 1)
    assert (world.visits["left_ed_at"] > world.visits["triage_at"]).all()


def test_weekly_p90_matches_pandas(con, admitted_weeks):
    dbt = _df(con, "select site_id, week_start, p90_los_hours, patients, share_within_target from site_week "
                    "where patient_group = 'admitted'")
    m = admitted_weeks.merge(dbt, on=["site_id", "week_start"], validate="one_to_one")
    assert len(m) == len(dbt) == len(SITES) * 44
    assert (m["n"] == m["patients"]).all()
    assert np.allclose(m["p90"], m["p90_los_hours"], atol=1e-9)
    assert np.allclose(m["within"], m["share_within_target"])


def test_daily_long_table_matches_pandas(con, world):
    v = world.visits.assign(day=world.visits["triage_at"].dt.date)
    visits = v.groupby(["site_id", "day"]).size()
    dbt = _df(con, "select site_id, day, value from fct_site_day_metric where metric = 'ed_visits'")
    dbt = dbt.set_index(["site_id", "day"])["value"]
    assert (dbt.loc[visits.index] == visits).all()
    occ = con.sql("select value from fct_site_day_metric where metric = 'bed_occupancy_rate'").df()["value"]
    assert occ.between(0.7, 1.06).all()


def test_weekly_p90_is_not_the_average_of_daily_p90s(con):
    """Averaging daily percentiles understates the week: the mart takes the percentile over the week's patients."""
    daily = _df(con, """select site_id, date_trunc('week', day)::date as week_start, avg(value) as avg_daily
                       from fct_site_day_metric where metric = 'p90_los_admitted_hours' and site_id = 'ED03'
                       group by 1, 2""")
    weekly = _df(con, "select site_id, week_start, p90_los_hours from site_week "
                       "where patient_group = 'admitted' and site_id = 'ED03'")
    m = daily.merge(weekly)
    assert (m["p90_los_hours"] - m["avg_daily"]).mean() > 0.2


def test_planted_patterns(con):
    w = _df(con, "select site_id, week_start, breached, reportable, min_staffed_beds from site_week "
                  "where patient_group = 'admitted'")
    by_site = w.groupby("site_id")
    assert by_site["breached"].mean()[CHRONIC_SITE] > 0.8
    assert by_site["breached"].mean().idxmax() == CHRONIC_SITE
    closure = w[w["site_id"] == CLOSURE_SITE]
    after = closure["week_start"] >= CLOSURE_START
    assert closure.loc[after, "breached"].all()
    assert closure.loc[~after, "breached"].mean() < 0.05
    assert closure.loc[after, "min_staffed_beds"].eq(SITES[CLOSURE_SITE].beds - CLOSED_BEDS).all()
    assert (~w.loc[w["site_id"] == SMALL_SITE, "reportable"]).sum() >= 40  # 43 of 44 weeks under 20 patients
    assert w.loc[w["site_id"] != SMALL_SITE, "reportable"].all()


def test_breaches_last_week(con, admitted_weeks):
    assert last_full_week(con) == date(2026, 11, 2)
    b = breaches(con)
    assert (b["week_start"], b["week_end"], b["target_hours"]) == ("2026-11-02", "2026-11-08", 8)
    truth = admitted_weeks[(admitted_weeks["week_start"] == date(2026, 11, 2)) & (admitted_weeks["n"] >= 20)]
    assert set(b["breached"]) == set(truth.loc[truth["p90"] > 8, "site_id"])
    assert CLOSURE_SITE in b["breached"] and CHRONIC_SITE in b["breached"]
    assert b["not_reported"] == [SMALL_SITE]
    assert [s["site_id"] for s in b["sites"]][-1] == SMALL_SITE  # unreported sites go last, not as passing
    reported = [s["p90_hours"] for s in b["sites"] if s["reported"]]
    assert reported == sorted(reported, reverse=True)


def test_breaches_other_week_and_group(con):
    before = breaches(con, date(2026, 10, 19))
    assert CLOSURE_SITE not in before["breached"]
    low = breaches(con, date(2026, 11, 2), group="low_urgency_sent_home")
    assert low["target_hours"] == 4
    assert breaches(con, date(2025, 1, 6))["sites"] == []


def test_breach_rule_on_a_hand_made_week(tmp_path):
    """Three sites, one week: over target, exactly on target, and too few patients."""
    path = tmp_path / "tiny.duckdb"
    with duckdb.connect(str(path)) as c:
        c.execute("create table site_week (site_id varchar, week_start date, patient_group varchar, "
                  "target_hours int, patients int, p90_los_hours double, share_within_target double, "
                  "mean_bed_occupancy double, min_staffed_beds int, reportable boolean, breached boolean)")
        c.execute("create table dim_sites (site_id varchar, site_type varchar, region varchar)")
        c.execute("insert into dim_sites values ('A', 't', 'r'), ('B', 't', 'r'), ('C', 't', 'r')")
        c.execute("""insert into site_week values
            ('A', '2026-11-02', 'admitted', 8, 40, 8.01, 0.89, 0.99, 100, true, true),
            ('B', '2026-11-02', 'admitted', 8, 40, 8.00, 0.90, 0.95, 100, true, false),
            ('C', '2026-11-02', 'admitted', 8, 19, 12.0, 0.50, 0.90, 30, false, false)""")
        b = breaches(c, date(2026, 11, 2))
    assert b["breached"] == ["A"] and b["not_reported"] == ["C"]


def test_public_file_is_the_pinned_version():
    raw = public.PATH.read_bytes()
    assert public.sha256(raw) == public.SHA256
    assert b"\r\n" in raw  # published with CRLF; .gitattributes keeps git from rewriting it
    d = public.read()
    assert (d["date"].min().date(), d["date"].max().date(), len(d)) == (date(2020, 5, 1), date(2024, 11, 20), 1665)


def test_public_file_tampering_is_refused(tmp_path):
    bad = tmp_path / "icu.csv"
    bad.write_bytes(public.PATH.read_bytes().replace(b"2012", b"2013", 1))
    with pytest.raises(ValueError, match="pinned"):
        public.read(bad)


def test_public_odd_days_are_found(con):
    s = _df(con, """select census_date, over_capacity, adult_patients_outlier from icu_province_day
                   where over_capacity or adult_patients_outlier order by 1""")
    days = [d.isoformat() for d in s["census_date"]]
    assert len(days) == 11
    assert days[-2:] == ["2023-09-09", "2023-10-20"]  # adult patients 560 and 2,870 against about 1,750 around them
    assert sum(d.startswith("2022-11") for d in days) == 9  # more paediatric ICU patients than paediatric beds
    assert con.sql("select count(*) from icu_province_day").fetchone()[0] == 1665


def test_committed_results_are_current(db):
    s = summary(db)
    assert SUMMARY.read_text() == to_json(s)
    assert SITE_WEEK.read_text() == site_week_csv(db)
    assert s["last_week"]["breached"] == ["ED07", "ED03", "ED06"]
    assert s["bed_closure"]["after"]["breached_weeks"] == 2
