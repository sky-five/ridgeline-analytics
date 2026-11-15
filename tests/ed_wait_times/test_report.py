"""The ED wait-times dashboard tables: they come from the committed results and the pinned public file, weekly
throughput adds back to the totals, a week too small to report never shows a 90th percentile, and the page reads
only tables (and columns) the export writes."""
import json
import re

import pandas as pd
import pytest

from ed_wait_times import public
from ed_wait_times.report import tables
from ed_wait_times.run import SITE_WEEK, SUMMARY

ROOT = SUMMARY.parents[2]
PAGE = ROOT / "reports" / "pages" / "ed-wait-times.md"
NIGHTLY = ROOT / ".github" / "workflows" / "nightly.yml"
EXPORT = ROOT / "scripts" / "export_reporting.py"
SOURCES = ROOT / "reports" / "sources" / "ridgeline"


@pytest.fixture(scope="module")
def t():
    return tables()


@pytest.fixture(scope="module")
def s():
    return json.loads(SUMMARY.read_text(encoding="utf-8"))


def test_export_writes_seven_tables(t):
    assert set(t) == {"ed_summary", "ed_last_week", "ed_sites", "ed_site_week", "ed_throughput_weekly",
                      "ed_icu_daily", "ed_icu_odd_days"}
    assert len(t["ed_summary"]) == 1
    assert len(t["ed_last_week"]) == len(t["ed_sites"]) == 10
    assert len(t["ed_site_week"]) == 10 * 44 * 3
    assert len(t["ed_throughput_weekly"]) == 10 * 44
    assert "ed_tables()" in EXPORT.read_text()
    for name in t:
        assert (SOURCES / f"{name}.sql").read_text().strip() == f"select * from reporting.{name}"


def test_weekly_throughput_adds_back_to_the_totals(t, s):
    w = t["ed_throughput_weekly"]
    assert w["visits"].sum() == s["simulated"]["visits"] == 475_391
    assert w["admitted"].sum() == s["simulated"]["admitted"] == 64_014
    sites = t["ed_sites"].set_index("site_id")
    by_site = w.groupby("site_id")[["visits", "admitted"]].sum()
    assert (by_site["visits"] == sites["visits"]).all() and (by_site["admitted"] == sites["admitted"]).all()
    assert w["share_admitted"].between(0, 1).all()
    # every week's visits are the three patient groups added up
    raw = pd.read_csv(SITE_WEEK).groupby(["site_id", "week_start"])["patients"].sum()
    assert sorted(raw.tolist()) == sorted(w["visits"].tolist())


def test_a_week_too_small_to_report_shows_no_90th_percentile(t, s):
    sw = t["ed_site_week"]
    assert sw["p90_reported_hours"].isna().equals(~sw["reportable"])
    assert not (sw["breached"] & ~sw["reportable"]).any()
    w = t["ed_throughput_weekly"]
    small = w[w["site_id"] == "ED10"]
    assert small["admitted_p90_hours"].isna().sum() == 43 == t["ed_summary"].iloc[0]["small_site_unreported_weeks"]
    assert w["admitted_p90_hours"].isna().sum() == sum(r["unreported_weeks"] for r in s["admitted_weeks_by_site"])


def test_the_bed_closure_shows_in_the_staffed_beds(t):
    ed07 = t["ed_throughput_weekly"].query("site_id == 'ED07'").set_index("week_start")["staffed_beds"]
    summ = t["ed_summary"].iloc[0]
    after = pd.Series(ed07.index >= summ["closure_from"], index=ed07.index)
    assert set(ed07[~after]) == {260} and set(ed07[after]) == {260 - summ["closed_beds"]} and after.sum() == 2


def test_last_week_matches_the_breach_query(t, s):
    lw = t["ed_last_week"].sort_values("sort")
    summ = t["ed_summary"].iloc[0]
    assert lw["site_id"].tolist() == [x["site_id"] for x in s["last_week"]["sites"]]
    assert lw.loc[lw["status"] == "over target", "site_id"].tolist() == ["ED07", "ED03", "ED06"]
    assert summ["breached_sites"] == "ED07, ED03, ED06" and summ["breached_last_week"] == 3
    assert lw.loc[lw["status"].str.startswith("not reported"), "site_id"].tolist() == ["ED10"]
    assert pd.isna(lw.set_index("site_id").loc["ED10", "p90_reported_hours"])
    assert (str(summ["week_start"]), str(summ["week_end"])) == ("2026-11-02", "2026-11-08")
    # the same week in the weekly table
    wk = t["ed_throughput_weekly"].query("week_start == @summ.week_start").set_index("site_id")
    for r in lw.itertuples():
        assert wk.loc[r.site_id, "admitted"] == r.patients


def test_the_page_numbers(t):
    summ = t["ed_summary"].iloc[0]
    assert (summ["closure_before_p90"], summ["closure_after_p90"]) == (5.66, 10.74)
    assert (summ["closure_before_breached"], summ["closure_before_weeks"]) == (1, 42)
    assert (summ["closure_after_breached"], summ["closure_after_weeks"]) == (2, 2)
    sites = t["ed_sites"].set_index("site_id")
    assert sites.loc["ED03", "breached_weeks"] == 39
    assert summ["icu_days"] == 1_665 and summ["icu_odd_days"] == 11 and summ["icu_median_adult_occupancy"] == 0.7418


def test_icu_days_are_the_public_file_with_its_odd_days_marked(t, s):
    d = t["ed_icu_daily"]
    raw = public.read()
    assert len(d) == len(raw) == 1_665
    assert (d["adult_patients"].to_numpy() == raw["total_adult_icu_patients"].to_numpy()).all()
    assert d["adult_occupancy"].median() == pytest.approx(s["public_icu"]["median_adult_occupancy"], abs=1e-4)
    odd = t["ed_icu_odd_days"].set_index("date")
    assert d["odd_day"].sum() == len(odd) == 11
    why = odd["why"].astype(str)
    assert why.str.contains("paediatric patients for").sum() == 10  # 9 in November 2022, and 2023-10-20
    assert why[pd.Timestamp("2023-10-20").date()].count(";") == 2
    assert why[pd.Timestamp("2023-09-09").date()] == "560 adult patients, far from the median of the week around it"


def test_page_reads_only_exported_tables_and_columns(t):
    page = PAGE.read_text(encoding="utf-8")
    assert set(re.findall(r"ridgeline\.(\w+)", page)) == set(t)
    queries = dict(re.findall(r"```sql (\w+)\nselect \* from ridgeline\.(\w+)", page))
    assert queries["summary"] == "ed_summary"
    for name, table in queries.items():
        cols = set(t[table].columns)
        for comp in re.findall(rf"<\w+ data={{{name}}}[^>]*>", page):
            for attr in ("value", "column", "x", "y"):
                for col in re.findall(rf"\b{attr}=(\w+)", comp):
                    assert col in cols, (name, attr, col)
    # columns picked by name in the other queries exist in the table they select from
    for block in re.findall(r"```sql \w+\n(.*?)```", page, flags=re.S):
        m = re.match(r"select (?!\*)(.*?)\s+from ridgeline\.(\w+)", block, flags=re.S)
        if not m:
            continue
        cols, table = m.groups()
        cols = re.sub(r"'[^']*'", "", re.sub(r"\(.*?\)", "", cols))
        for col in re.findall(r"\b([a-z_]+)\b", cols):
            if col not in ("as", "value", "label", "distinct", "week", "unit", "occupancy", "strftime"):
                assert col in t[table].columns, (table, col)


def test_nightly_smoke_test_opens_the_page():
    assert re.search(r"for page in .* ed-wait-times/", NIGHTLY.read_text())
