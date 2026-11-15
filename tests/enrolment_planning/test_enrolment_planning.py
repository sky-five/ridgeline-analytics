"""Checks the public files as committed, the extract and the IRCC parser on hand-made input, the dbt marts against
pandas counts from the raw files, the forecasting rules on a hand-made series (and that they never look past
the origin), and the committed results."""
import json
import shutil

import duckdb
import pandas as pd
import pytest

from enrolment_planning import forecast, public
from enrolment_planning.run import SCORES, SUMMARY, scores_csv, summary, to_json


@pytest.fixture(scope="module")
def con(db):
    with duckdb.connect(str(db), read_only=True) as c:
        yield c


# --- the public files -------------------------------------------------------------------------------------------

def test_committed_files_match_their_pins():
    for path in (public.ENROLMENTS, public.TOTALS, public.PERMITS):
        assert public.sha256(path.read_bytes()) == public.SHA256[path.name]


def test_a_changed_file_is_refused(tmp_path):
    bad = tmp_path / public.PERMITS.name
    shutil.copy(public.PERMITS, bad)
    with open(bad, "ab") as f:
        f.write(b"\0")
    with pytest.raises(ValueError, match="pinned SHA-256"):
        public.permits(bad)


def test_permit_months_add_up_to_a_little_more_than_the_sheets_yearly_totals():
    """The sheet carries IRCC's yearly totals. A person whose permit became effective in two months of a year
    counts in both months but once in the year, so the 12 parsed months of the all-Canada post-secondary row add
    up to more than the year's total, in every year, by 2% to 5.2%. A parsing slip (a wrong row or month) would
    break that band."""
    raw = pd.read_excel(public.PERMITS, header=None)
    row = next(i for i in range(len(raw)) if raw.iat[i, 0] == "Post Secondary")
    p = public.permits()
    ca = p[(p.region == "CA") & (p.study_level == "post_secondary")]
    by_year = ca.groupby(pd.to_datetime(ca.month).dt.year)["permits"].sum()
    for year, months in by_year.items():
        col = next(c for c in raw.columns if f"{year} Total" in (raw.iat[2, c], raw.iat[3, c]))
        published = float(str(raw.iat[row, col]).replace(",", ""))
        assert 1.02 <= months / published <= 1.052, year


def test_permits_parser_reads_suppressed_cells_and_every_region():
    p = public.permits()
    assert p.loc[p.suppressed, "permits"].isna().all()
    assert p.loc[~p.suppressed, "permits"].notna().all()
    assert (p.loc[~p.suppressed, "permits"] % 5 == 0).all()  # IRCC rounds to multiples of 5
    assert set(p.region) == set(public.REGIONS.values())
    assert set(p.loc[p.region == "TR", "region_name"]) == {"Yukon", "Northwest Territories", "Nunavut"}


def test_extract_keeps_only_leaves_and_codes_them(tmp_path):
    """build_extract on a few hand-made rows in StatCan's layout."""
    header = ('"REF_DATE","GEO","DGUID","International Standard Classification of Education (ISCED)",'
              '"Institution type","Classification of Instructional Programs, STEM and BHASE groupings",'
              '"Status of student in Canada","Age group","Gender","Selected academic period",'
              '"Selected statistics","UOM","UOM_ID","SCALAR_FACTOR","SCALAR_ID","VECTOR","COORDINATE","VALUE",'
              '"STATUS","SYMBOL","TERMINATED","DECIMALS"')

    def row(geo, level, inst, program, status, value, age="Total, age group", stat="Number"):
        return ",".join(f'"{v}"' for v in ["2023/2024", geo, "x", level, inst, program, status, age,
                                           "Total, gender", "Fall snapshot", stat, "Number", "223", "units", "0",
                                           "v1", "1", value, "", "", "", "0"])
    lines = [header,
             row("Ontario", "Master's or equivalent", "University", "Business and administration [b.1]",
                 "International students", "300"),
             row("Ontario", "Master's or equivalent", "University", "Unclassified, instructional program",
                 "Canadian students", ".."),
             row("Ontario", "Master's or equivalent", "University", "STEM [a]", "Canadian students", "999"),
             row("Canada", "Master's or equivalent", "University", "Business and administration [b.1]",
                 "International students", "300"),
             row("Ontario", "Master's or equivalent", "University", "Business and administration [b.1]",
                 "International students", "50", age="20 to 24 years"),
             row("Ontario", "Total, International Standard Classification of Education (ISCED)",
                 "Total, institution type", "Total, instructional program", "International students", "300"),
             row("Ontario", "Total, International Standard Classification of Education (ISCED)",
                 "Total, institution type", "Total, instructional program", "International students", "12.5",
                 stat="Proportion of Canadian and international enrolments")]
    src = tmp_path / "t.csv"
    src.write_text("\n".join(lines) + "\n")
    leaves, totals = public.build_extract(src)
    assert leaves.splitlines() == ["fall_year,region,isced,institution,program,status,enrolments",
                                   "2023,ON,7,U,b.1,INT,300", "2023,ON,7,U,u,CAN,"]
    assert totals.splitlines() == ["fall_year,region,status,enrolments", "2023,ON,INT,300"]


# --- the marts --------------------------------------------------------------------------------------------------

def test_fact_matches_the_raw_extract(con):
    raw = public.enrolments().groupby(["fall_year", "status"])["enrolments"].sum()
    fct = con.sql("select fall_year, status_code as status, sum(enrolments) as n from fct_enrolment group by 1, 2"
                  ).df().set_index(["fall_year", "status"])["n"]
    fct.index = fct.index.set_levels(fct.index.levels[0].astype("int64"), level=0)
    pd.testing.assert_series_equal(raw.sort_index(), fct.sort_index().astype(raw.dtype), check_names=False)
    assert con.sql("select count(*) from fct_enrolment").fetchone()[0] == len(public.enrolments())


def test_every_fact_row_joins_to_every_dimension(con):
    n = con.sql("""select count(*) from fct_enrolment
                   join dim_term using (fall_year) join dim_region using (region_code)
                   join dim_level using (isced_code) join dim_institution using (institution_code)
                   join dim_program using (program_code) join dim_status using (status_code)""").fetchone()[0]
    assert n == con.sql("select count(*) from fct_enrolment").fetchone()[0]


def test_national_leaves_are_within_rounding_of_the_published_canada_totals(con):
    """No Canada rows go into the fact; the provinces' leaves added up must land on StatCan's own national total
    within the random rounding (each cell moves by at most 2)."""
    df = con.sql("""with leaves as (select fall_year, status_code, sum(enrolments) as n, count(*) as cells
                                    from fct_enrolment where not is_not_available group by 1, 2)
                    select l.*, t.published_enrolments from leaves l join stg_statcan__totals t
                    using (fall_year, status_code) where t.region_code = 'CA'""").df()
    assert len(df) == 15 * 3
    assert ((df.n - df.published_enrolments).abs() <= 2 * (df.cells + 1)).all()
    big = df[df.status_code != "NR"]
    assert ((big.n - big.published_enrolments).abs() / big.published_enrolments).max() < 0.001


def test_territories_are_added_up_and_suppressed_cells_count_as_none(con):
    p = public.permits()
    tr = p[(p.region == "TR") & (p.study_level == "post_secondary")].groupby("month")["permits"].sum()
    fct = con.sql("""select permit_month, permits, permits_suppressed_cells from fct_study_permits_month
                     where region_code = 'TR' and study_level = 'post_secondary' order by 1""").df()
    assert fct.permits.tolist() == tr.astype(int).tolist()
    assert fct.permits_suppressed_cells.sum() == p[(p.region == "TR") & (p.study_level == "post_secondary")
                                                   ].suppressed.sum()


# --- the rules --------------------------------------------------------------------------------------------------

def _series(values, start="2015-01"):
    return pd.Series([float(v) for v in values], index=pd.period_range(start, periods=len(values), freq="M"))


def test_rules_on_a_hand_made_series():
    # 2015: 100 a month, 2016: 120, 2017: 150; forecast 2018 from origin 2017-12.
    y = _series([100] * 12 + [120] * 12 + [150] * 12)
    o = pd.Period("2017-12", "M")
    assert forecast.forecast(y, o, "same_month_last_year", 3) == 150
    assert forecast.forecast(y, o, "last_year_with_trend", 3) == pytest.approx(150 * 150 / 120)
    assert forecast.forecast(y, o, "three_year_mean", 12) == pytest.approx((100 + 120 + 150) / 3)
    with pytest.raises(ValueError):
        forecast.forecast(y, o, "moving_average", 1)


def test_rules_never_use_months_after_the_origin():
    rng = pd.Series(range(1, 61), dtype=float)
    y = _series(rng)
    o = pd.Period("2017-12", "M")
    changed = y.copy()
    changed[changed.index > o] *= 10
    for rule in forecast.RULES:
        for h in forecast.HORIZONS:
            assert forecast.forecast(y, o, rule, h) == forecast.forecast(changed, o, rule, h)


def test_backtest_covers_every_origin_and_scores_add_up():
    y = _series([100 + i for i in range(48)])  # 2015-01 to 2018-12
    bt = forecast.backtest(y, "X")
    # origins 2017-12 .. 2018-11; origin k months after 2017-12 has 12 - k targets left
    assert len(bt) == sum(12 - k for k in range(12)) * len(forecast.RULES)
    assert bt["target"].max() == pd.Period("2018-12", "M")
    assert (bt["target"] - bt["origin"]).map(lambda d: d.n).eq(bt["horizon"]).all()
    yearly = forecast.next_12_months(bt)
    assert list(yearly["origin"].unique()) == [pd.Period("2017-12", "M")]
    snl = yearly[yearly.rule == "same_month_last_year"].iloc[0]
    assert snl.forecast == sum(100 + i for i in range(24, 36)) and snl.actual == sum(100 + i for i in range(36, 48))
    s = forecast.score(yearly, ["rule"]).set_index("rule")
    assert s.loc["same_month_last_year", "wape"] == pytest.approx(abs(snl.forecast - snl.actual) / snl.actual)
    assert s.loc["same_month_last_year", "bias"] < 0


# --- the committed results --------------------------------------------------------------------------------------

def test_committed_results_are_current(db):
    assert SUMMARY.read_text() == to_json(summary(db))
    assert SCORES.read_text() == scores_csv(db)


def test_headline_numbers_quoted_in_the_readme():
    s = json.loads(SUMMARY.read_text())
    e = s["enrolments"]
    assert (e["last_fall"], e["international"], e["total"]) == (2024, 533382, 2345775)
    assert (e["peak_international_fall"], e["peak_international"]) == (2023, 572967)
    assert round(e["international_share"], 3) == 0.227 and round(e["first_fall_international_share"], 3) == 0.072
    best = {(b["series"], b["period"]): b for b in s["backtest"]["next_12_months_best_rule"]}
    cap = best[("CA", "2024-2026 after the cap")]
    assert (cap["rule"], round(cap["wape"], 3), round(cap["bias"], 3)) == ("same_month_last_year", 0.352, 0.245)
    assert best[("CA", "2020-2021 pandemic")]["rule"] == "three_year_mean"
    # after the cap 14 of the 15 series and rules forecast too many; the one under is Alberta's three-year mean
    scores = pd.read_csv(SCORES)
    after = scores[(scores.measure == "next_12_months") & (scores.period == "2024-2026 after the cap")]
    assert len(after) == 5 * 3
    under = after[after.bias <= 0]
    assert list(zip(under.series, under.rule, strict=True)) == [("AB", "three_year_mean")]
    ca = after[after.series == "CA"].set_index("rule")["bias"]
    assert ca.min() > 0.18 and ca.max() < 0.31
