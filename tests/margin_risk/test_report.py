"""The margin risk dashboard: the new results files are what the marts give, the reporting tables add up (calls to
the summary, sectors to the whole book, snapshots to the sector totals, flagged days to the planted faults), every
query on the page runs against the exported tables, and the page's fixed words match the simulation."""
import json
import re

import duckdb
import pandas as pd
import pytest

from margin_risk.report import SNAPSHOT_ORDER, tables
from margin_risk.run import (
    CONCENTRATION,
    MARGIN_CALLS,
    SECTOR_DAILY,
    SUMMARY,
    concentration_csv,
    margin_calls_csv,
    sector_daily_csv,
    snapshot_days,
)
from margin_risk.simulate import (
    CONCENTRATION_RATE,
    INITIAL_RATE,
    SECTORS,
    SHOCK_DAYS,
    SHOCK_SECTOR,
    SPLIT_DATE,
)

ROOT = SUMMARY.parents[2]
PAGE = ROOT / "reports" / "pages" / "margin-risk.md"
NIGHTLY = ROOT / ".github" / "workflows" / "nightly.yml"
EXPORT = ROOT / "scripts" / "export_reporting.py"
SOURCES = ROOT / "reports" / "sources" / "ridgeline"
NAMES = {"margin_summary", "margin_daily", "margin_calls", "margin_calls_daily", "margin_call_outcomes",
         "margin_sectors", "margin_concentration", "margin_reconciliation"}


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
    assert MARGIN_CALLS.read_text() == margin_calls_csv(db)
    assert SECTOR_DAILY.read_text() == sector_daily_csv(db)
    assert CONCENTRATION.read_text() == concentration_csv(db)


def test_export_writes_eight_tables(t):
    assert set(t) == NAMES
    assert len(t["margin_summary"]) == 1
    assert len(t["margin_daily"]) == len(t["margin_calls_daily"]) == 128
    assert len(t["margin_sectors"]) == 6 * 128
    assert len(t["margin_concentration"]) == 4 * 30
    assert "margin_tables()" in EXPORT.read_text()
    for name in t:
        assert (SOURCES / f"{name}.sql").read_text().strip() == f"select * from reporting.{name}"


def test_calls_add_up_to_the_summary(t, s):
    calls, daily, outcomes = t["margin_calls"], t["margin_calls_daily"], t["margin_call_outcomes"]
    c = s["margin_calls"]
    real = calls[calls["real"]]
    assert (len(calls), len(real)) == (c["calls"], c["calls"] - c["on_a_break"]) == (69, 62)
    # the calls that are not real all start on the day the split was applied late
    assert set(calls.loc[~calls["real"], "call_date"]) == {SPLIT_DATE}
    assert daily["real_calls"].sum() == 62 and daily["calls_on_a_break"].sum() == 7
    assert (daily["real_calls"] + daily["calls_on_a_break"] == daily["new_calls"]).all()
    assert outcomes["calls"].sum() == 62
    assert outcomes["deficit_at_call"].sum() == pytest.approx(c["deficit_at_call"], abs=0.01)
    by = outcomes.set_index("resolution_label")["calls"]
    assert (by["Deposit"], by["Liquidation"], by["Prices recovered"], by["Still open"]) == (18, 24, 19, 1)
    week = daily[(daily["as_of_date"] >= SHOCK_DAYS[0].date())
                 & (daily["as_of_date"] <= (SHOCK_DAYS[-1] + pd.Timedelta(days=7)).date())]
    assert week["real_calls"].sum() == s["shock"]["real_calls_within_a_week"] == 10
    assert daily.loc[daily["as_of_date"] < SHOCK_DAYS[0].date(), "real_calls"].sum() == 0


def test_page_claim_every_real_call_is_concentrated_in_semiconductors(t, s):
    real = t["margin_calls"][t["margin_calls"]["real"]]
    assert real["was_concentrated"].all() and (real["top_sector"] == SHOCK_SECTOR).all()
    assert s["margin_calls"]["concentrated"] == s["margin_calls"]["top_in_semiconductors"] == len(real)


def test_sectors_add_up_to_the_book(t, s):
    sec = t["margin_sectors"]
    shares = sec.groupby("as_of_date")["share_of_borrower_value"].sum()
    assert shares.between(0.999, 1.001).all()
    last = sec[sec["as_of_date"].astype(str) == s["as_of"]].set_index("sector")
    assert last.loc[SHOCK_SECTOR, "share_of_borrower_value"] == pytest.approx(s["shock_sector"]["share"], abs=1e-4)
    assert last.loc[SHOCK_SECTOR, "borrowers_concentrated"] == s["shock_sector"]["concentrated"]
    semis = sec[sec["sector"] == SHOCK_SECTOR].set_index("as_of_date")["share_of_borrower_value"]
    before, after = (semis[d] for d in pd.to_datetime(list(snapshot_days().values())[1:3]).date)
    assert after < before - 0.05  # the sell-off shrinks the sector by more than five points of the book


def test_snapshots_add_up_to_their_sectors(t, s):
    conc, sec = t["margin_concentration"], t["margin_sectors"]
    days = snapshot_days()
    assert list(days) == SNAPSHOT_ORDER
    assert days["before the sell-off"] == "2026-03-13" and days["end of the sell-off"] == "2026-03-20"
    assert sorted(set(conc["as_of_date"].astype(str))) == sorted(days.values())
    rolled = conc.groupby(["as_of_date", "sector"])[["borrower_market_value", "share_of_borrower_value"]].sum()
    kept = sec[sec["as_of_date"].isin(conc["as_of_date"])].set_index(["as_of_date", "sector"])
    assert rolled["borrower_market_value"].to_numpy() == pytest.approx(
        kept.loc[rolled.index, "borrower_market_value"].to_numpy(), abs=0.05)
    top = conc[conc["snapshot"] == "last day"].sort_values("share_of_borrower_value").iloc[-1]
    assert (top["symbol"], top["share_of_borrower_value"]) == (s["largest_holding"]["symbol"], 0.071)


def test_reconciliation_table_is_the_planted_faults(t, s):
    r = t["margin_reconciliation"].set_index("fault")
    assert (r["accounts_broken"] == r["planted"]).all()
    assert r.loc["split_applied_late", "market_value_drift"] == -418_102.89
    assert r.loc["interest_missing_from_cash_file", "cash_drift"] == 80_589.39
    assert (r["pnl_unexplained"] == r["market_value_drift"] + r["cash_drift"]).all()
    flagged = t["margin_daily"].loc[t["margin_daily"]["reconciliation_flagged"], "as_of_date"]
    assert sorted(flagged) == sorted(r["as_of_date"])
    assert "Not explained yet" not in set(r["cause"])


def _queries(page: str) -> dict[str, str]:
    return dict(re.findall(r"```sql (\w+)\n(.*?)```", page, flags=re.S))


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


def test_every_page_query_runs_on_the_exported_tables(page, site):
    queries = _queries(page)
    assert set(re.findall(r"ridgeline\.(\w+)", page)) == NAMES
    for name, sql in queries.items():
        if "${inputs.snapshot.value}" in sql:
            for snap in SNAPSHOT_ORDER:
                assert len(site.sql(sql.replace("${inputs.snapshot.value}", snap)).fetchall()) == 30, (name, snap)
        else:
            assert site.sql(sql).fetchall(), name
    assert 'defaultValue="last day"' in page


def test_page_components_use_existing_columns(t, page, site):
    queries = _queries(page)
    summary_cols = set(t["margin_summary"].columns)
    for comp in re.findall(r"<(?:BigValue|Value) data=\{summary\}[^>]*>", page):
        for col in re.findall(r"\b(?:value|column)=(\w+)", comp):
            assert col in summary_cols, col

    def columns(name: str) -> set[str]:
        sql = queries[name].replace("${inputs.snapshot.value}", "last day")
        return {c[0] for c in site.sql(sql).description}

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


def test_page_words_match_the_simulation(page):
    page = " ".join(page.split())  # the page wraps its lines
    rates = sorted({rate for _, rate in SECTORS.values()})
    assert f"({rates[0]:.0%} or {rates[1]:.0%} by sector, {CONCENTRATION_RATE:.0%} for a holding over half" in page
    assert f"at the {INITIAL_RATE:.0%} initial rate" in page
    assert f"30 fictional securities in {len(SECTORS)} sectors" in page
    sell_off = re.findall(r"<ReferenceArea xMin='([\d-]+)' xMax='([\d-]+)'", page)
    assert len(sell_off) == 3
    assert set(sell_off) == {(str(SHOCK_DAYS[0].date()), str(SHOCK_DAYS[-1].date()))}


def test_nightly_smoke_test_opens_the_page():
    assert re.search(r"for page in .* margin-risk/", NIGHTLY.read_text())
