"""The book health dashboard: the new results files are what the marts and the back-test give, the reporting tables
add up (provinces to the book, segments to the rate actions, the back-test path to its scores, the forecast to the
summary, the brief to brief.md), every query on the page runs against the exported tables, and the page's fixed
words and marked dates match the simulation."""
import json
import re

import duckdb
import pandas as pd
import pytest

from book_health.report import RULE_LABELS, WHOLE_BOOK, brief_rows, tables
from book_health.run import (
    BACKTEST_PATH,
    BRIEF,
    SEGMENT_WATCH,
    SUMMARY,
    backtest,
    backtest_path_csv,
    segment_watch_csv,
)
from book_health.simulate import AS_OF, HAIL_DATE, NORMAL_RATE_CHANGE, RATE_ACTIONS

ROOT = SUMMARY.parents[2]
PAGE = ROOT / "reports" / "pages" / "book-health.md"
NIGHTLY = ROOT / ".github" / "workflows" / "nightly.yml"
EXPORT = ROOT / "scripts" / "export_reporting.py"
SOURCES = ROOT / "reports" / "sources" / "ridgeline"
NAMES = {"book_summary", "book_provinces", "book_province_month", "book_channels", "book_segments",
         "book_rate_actions", "book_backtest", "book_backtest_path", "book_forecast", "book_brief"}


@pytest.fixture(scope="module")
def t():
    return tables()


@pytest.fixture(scope="module")
def s():
    return json.loads(SUMMARY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def page():
    return PAGE.read_text(encoding="utf-8")


def test_new_results_files_are_what_the_marts_give(db):
    assert SEGMENT_WATCH.read_text() == segment_watch_csv(db)
    assert BACKTEST_PATH.read_text() == backtest_path_csv(backtest(db))


def test_export_writes_ten_tables(t, s):
    assert set(t) == NAMES
    assert len(t["book_summary"]) == 1
    assert len(t["book_provinces"]) == 8
    assert len(t["book_province_month"]) == 8 * s["book"]["months"] == 432
    assert len(t["book_segments"]) == len(RATE_ACTIONS) * 54
    assert len(t["book_rate_actions"]) == 2 * len(RATE_ACTIONS)
    assert len(t["book_forecast"]) == 8 * 3
    assert "book_tables()" in EXPORT.read_text()
    for name in t:
        assert (SOURCES / f"{name}.sql").read_text().strip() == f"select * from reporting.{name}"


def test_provinces_add_up_to_the_book(t, s):
    pm, b = t["book_province_month"], s["book"]
    last = pm[pm["month_start"] == pm["month_start"].max()]
    assert last["policies_in_force"].sum() == b["in_force"] == t["book_provinces"]["policies_in_force"].sum()
    year = pm[pm["month_start"] > (pd.Timestamp(AS_OF) - pd.DateOffset(months=12)).date()]
    assert year["written_premium"].sum() == pytest.approx(b["written_premium_12m"], abs=0.05)
    assert year["renewed"].sum() / year["renewals_due"].sum() == pytest.approx(b["retention_12m"], abs=1e-4)
    assert year["incurred"].sum() / year["earned_premium"].sum() == pytest.approx(b["loss_ratio_12m"], abs=1e-4)


def test_segments_are_part_of_their_province_and_give_the_rate_actions(t):
    seg, pm, ra = t["book_segments"], t["book_province_month"], t["book_rate_actions"]
    prov = pm.set_index(["province", "month_start"])
    for (p, month), row in seg.set_index(["province", "month_start"]).iterrows():
        assert row["renewals_due"] <= prov.loc[(p, month), "renewals_due"]
        assert row["incurred"] <= prov.loc[(p, month), "incurred"] + 0.005
    for p, prod, start, change in RATE_ACTIONS:
        one = seg[(seg["province"] == p) & (seg["product"] == prod)]
        for period, lo, hi in (("12 months before", start - pd.DateOffset(months=12), start),
                               ("12 months after", start, start + pd.DateOffset(months=12))):
            w = one[(one["month_start"] >= pd.Timestamp(lo).date()) & (one["month_start"] < pd.Timestamp(hi).date())]
            r = ra[(ra["province"] == p) & (ra["period"] == period)].iloc[0]
            assert w["renewals_due"].sum() == r["renewals_due"]
            assert w["renewed"].sum() / w["renewals_due"].sum() == pytest.approx(r["retention"], abs=1e-4)
        after = ra[(ra["province"] == p) & (ra["period"] == "12 months after")].iloc[0]
        assert after["mean_rate_change"] == pytest.approx(change, abs=0.005)


def test_hail_month_is_the_segment_table_peak(t, s):
    ab = t["book_segments"][t["book_segments"]["segment"] == "Alberta home"].set_index("month_start")
    hail_month = HAIL_DATE.replace(day=1)
    assert ab["loss_ratio"].idxmax() == hail_month
    assert ab.loc[hail_month, "loss_ratio"] == s["hail"]["home_loss_ratio_that_month"] == 5.508


def test_backtest_path_gives_the_one_month_scores(t):
    path, scores = t["book_backtest_path"], t["book_backtest"]
    assert set(path["rule_label"]) == set(RULE_LABELS.values())
    assert WHOLE_BOOK in set(path["province_name"])
    one = scores[scores["horizon"] == 1].set_index(["province", "rule"])
    for (p, rule), g in path.groupby(["province", "rule"]):
        err = (g["forecast"] - g["actual"]) * g["renewals_due"]
        assert len(g) == one.loc[(p, rule), "forecasts"]
        # the path is rounded to 4 places, the scores to 2: they agree within a hundredth of a point
        assert 100 * err.abs().sum() / g["renewals_due"].sum() == pytest.approx(one.loc[(p, rule), "mae_points"],
                                                                                 abs=0.011)
        assert 100 * err.sum() / g["renewals_due"].sum() == pytest.approx(one.loc[(p, rule), "bias_points"],
                                                                          abs=0.011)


def test_forecast_adds_up_to_the_summary(t, s):
    fc, row = t["book_forecast"], t["book_summary"].iloc[0]
    nxt = s["retention_forecast"]["next_3_months"]
    assert fc["renewals_due"].sum() == nxt["renewals_due"] == row["next_3_due"] == 5475
    assert fc["expected_renewed"].sum() == pytest.approx(nxt["expected_renewed"], abs=0.05)
    assert sorted(set(fc["month"])) == ["2026-07", "2026-08", "2026-09"]
    assert row["rule"] == RULE_LABELS[s["retention_forecast"]["rule"]] == "12-month average"


def test_brief_rows_are_the_brief(t):
    rows = t["book_brief"]
    text = BRIEF.read_text(encoding="utf-8")
    assert len(rows) == text.count("\n- ") == 11
    assert rows.groupby("section", sort=False).size().to_dict() == {
        "What the numbers say": 6, "Two cautions": 2, "So what": 3}
    assert not rows["body"].str.contains(r"\*\*").any() and not rows["lead"].str.contains(r"\*\*").any()
    assert (rows["lead"] != "").sum() == 8
    one = brief_rows("## A\n\n- **Lead.** rest\n- plain\n")
    assert one.to_dict("records") == [{"section": "A", "item_sort": 0, "lead": "Lead.", "body": "rest"},
                                      {"section": "A", "item_sort": 1, "lead": "", "body": "plain"}]


def _queries(page: str) -> dict[str, str]:
    return dict(re.findall(r"```sql (\w+)\n(.*?)```", page, flags=re.S))


def _fill(sql: str, province: str = "Ontario") -> str:
    return sql.replace("${inputs.province.value}", province)


@pytest.fixture(scope="module")
def site(t):
    """The exported tables in a DuckDB schema named like the page's source."""
    with duckdb.connect() as con:
        con.execute("create schema ridgeline")
        for name, df in t.items():
            con.register("_df", df)
            con.execute(f"create table ridgeline.{name} as select * from _df")
            con.unregister("_df")
        yield con


def test_every_page_query_runs_on_the_exported_tables(page, site, t):
    queries = _queries(page)
    assert set(re.findall(r"ridgeline\.(\w+)", page)) == NAMES
    for name, sql in queries.items():
        if "${inputs.province.value}" in sql:
            for province in t["book_backtest_path"]["province_name"].unique():
                assert site.sql(_fill(sql, province)).fetchall(), (name, province)
        else:
            assert site.sql(sql).fetchall(), name
    assert 'defaultValue="Ontario"' in page


def test_page_components_use_existing_columns(t, page, site):
    queries = _queries(page)
    summary_cols = set(t["book_summary"].columns)
    for comp in re.findall(r"<(?:BigValue|Value) data=\{summary\}[^>]*>", page):
        for col in re.findall(r"\b(?:value|column)=(\w+)", comp):
            assert col in summary_cols, col

    def columns(name: str) -> set[str]:
        return {c[0] for c in site.sql(_fill(queries[name])).description}

    for name, attrs in re.findall(r"<(?:BarChart|LineChart|AreaChart|Dropdown) data=\{(\w+)\}(.*?)/?>", page,
                                  flags=re.S):
        cols = columns(name)
        for listed, single in re.findall(r"\b(?:x|y|value|label|series)=(?:\{\[(.*?)\]\}|(\w+))", attrs):
            for col in re.findall(r"'([^']+)'", listed) if listed else [single]:
                assert col in cols, (name, col)
    for name, body in re.findall(r"<DataTable data=\{(\w+)\}[^>]*>(.*?)</DataTable>", page, flags=re.S):
        cols = columns(name)
        for col in re.findall(r"<Column id=(\w+)", body):
            assert col in cols, (name, col)
    for name, field in re.findall(r"\{#each (\w+) as b\}.*?\{b\.(\w+)\}", page, flags=re.S):
        assert field in columns(name), (name, field)


def test_page_words_and_dates_match_the_simulation(page, t, s):
    flat = " ".join(page.split())  # the page wraps its lines
    assert f"most land near {NORMAL_RATE_CHANGE:.0%}" in flat
    (ab_p, _, ab_from, ab_change), (on_p, _, on_from, on_change) = RATE_ACTIONS
    assert f"Alberta home renewals took about {ab_change:.0%}" in flat and ab_p == "AB"
    assert f"Ontario auto about {on_change:.0%}" in flat and on_p == "ON"
    lines = set(re.findall(r"<ReferenceLine x='([\d-]+)'", page))
    assert lines == {HAIL_DATE.replace(day=1).isoformat(), ab_from.isoformat(), on_from.isoformat()}
    assert f"label=\"Ontario auto +{on_change:.0%}\"" in page
    # the late-claims band covers the three months the summary's caution is about
    band = re.findall(r"<ReferenceArea xMin='([\d-]+)' xMax='([\d-]+)'", page)
    first = (pd.Timestamp(AS_OF).to_period("M") - 2).start_time.date().isoformat()
    assert band == [(first, AS_OF.replace(day=1).isoformat())]
    # the yearly loss-ratio chart keeps only full years
    assert f"year(month_start) <= {AS_OF.year - 1}" in page and AS_OF.month < 12
    # "Ontario is the only province with fewer ... Written premium still grew everywhere"
    prov = t["book_provinces"]
    assert list(prov.loc[prov["in_force_growth_yoy"] < 0, "province_name"]) == ["Ontario"]
    assert (prov["written_premium_growth_12m"] > 0).all()
    # "The four small provinces have under a hundred renewals due a month ... the whole book within about a point"
    pm = t["book_province_month"]
    assert pm[pm["province"].isin(["MB", "NB", "NS", "SK"])]["renewals_due"].max() < 100
    assert pm.groupby("province")["renewals_due"].max().sort_values().iloc[4] >= 100
    whole = t["book_backtest"].query("province == 'all' and horizon == 1")
    assert whole["mae_points"].max() < 1.0
    # "the 3-month average caught up faster"
    assert s["retention_forecast"]["ontario_first_6_months_after_rate_action"][1]["rule"] == "trailing_3"
    row = t["book_summary"].iloc[0]
    assert row["on_bias_trailing_3"] < row["on_bias_trailing_12"]


def test_nightly_smoke_test_opens_the_page():
    assert re.search(r"for page in .* book-health/", NIGHTLY.read_text())
