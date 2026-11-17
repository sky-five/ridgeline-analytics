"""The lead-cost dashboard: the new results files are what the warehouse gives, the reporting tables agree with each
other and with summary.json (client and campaign costs, attribution mix, weekly spend, the load audit, the faults),
every query on the page runs against the exported tables for every client, and the page's fixed words match the
data."""
import json
import re

import duckdb
import pandas as pd
import pytest

from lead_cost.report import ATTRIBUTED_BY, DEMOS_INCOMPLETE_FROM, SOURCE_LABELS, tables
from lead_cost.run import (
    LEAD_MIX,
    LOAD_AUDIT,
    SUMMARY,
    WEEKLY_COST,
    lead_mix_csv,
    load_audit_csv,
    weekly_cost_csv,
)
from lead_cost.simulate import CLIENTS

ROOT = SUMMARY.parents[2]
PAGE = ROOT / "reports" / "pages" / "lead-cost.md"
NIGHTLY = ROOT / ".github" / "workflows" / "nightly.yml"
EXPORT = ROOT / "scripts" / "export_reporting.py"
SOURCES = ROOT / "reports" / "sources" / "ridgeline"
NAMES = {f"lead_cost_{n}" for n in
         ("summary", "clients", "campaigns", "attribution", "weekly", "exports", "load_audit", "faults")}


@pytest.fixture(scope="module")
def t():
    return tables()


@pytest.fixture(scope="module")
def s():
    return json.loads(SUMMARY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def page():
    return PAGE.read_text(encoding="utf-8")


def test_new_results_files_are_what_the_warehouse_gives(lead_db):
    assert LOAD_AUDIT.read_text() == load_audit_csv(lead_db)
    assert LEAD_MIX.read_text() == lead_mix_csv(lead_db)
    assert WEEKLY_COST.read_text() == weekly_cost_csv(lead_db)


def test_export_writes_eight_tables(t):
    assert set(t) == NAMES
    assert len(t["lead_cost_summary"]) == 1 and len(t["lead_cost_clients"]) == len(CLIENTS) == 4
    assert len(t["lead_cost_campaigns"]) == 11 and len(t["lead_cost_faults"]) == 4
    assert len(t["lead_cost_load_audit"]) == 548 and len(t["lead_cost_exports"]) == len(SOURCE_LABELS)
    assert len(t["lead_cost_weekly"]) == 14 * len(CLIENTS)
    assert "lead_cost_tables()" in EXPORT.read_text()
    for name in t:
        assert (SOURCES / f"{name}.sql").read_text().strip() == f"select * from reporting.{name}"


def test_summary_agrees_with_the_results(t, s):
    row = t["lead_cost_summary"].iloc[0]
    h = s["headline"]
    assert (row["spend"], row["issued_leads"], row["demos"]) == (213675.83, 891, 439)
    assert row["cost_per_issued_lead"] == h["cost_per_issued_lead"] == 239.82
    assert row["cost_per_demo"] == round(h["spend"] / h["paid_demos"], 2) == 486.73
    assert row["leads"] == row["paid_leads"] + row["unattributed_leads"] == 2826
    assert row["unattributed_leads"] == row["organic_leads"] + row["paid_unattributed"] == 807
    assert (row["wrong_campaign"], row["outcome_mismatches"]) == (0, 0)
    assert (row["faults"], row["faults_caught"]) == (4, 4)


def test_clients_and_campaigns_add_up_to_the_headline(t, s):
    c, k = t["lead_cost_clients"], t["lead_cost_campaigns"]
    assert round(c["spend"].sum(), 2) == round(k["spend"].sum(), 2) == s["headline"]["spend"]
    assert c["issued_leads"].sum() == k["issued_leads"].sum() == s["headline"]["paid_issued_leads"]
    assert dict(zip(c["client"], c["cost_per_issued_lead"], strict=True)) == \
        s["headline"]["cost_per_issued_lead_by_client"]
    assert set(c["client_label"]) == {v[0] for v in CLIENTS.values()}
    assert k["campaign_label"].is_unique


def test_attribution_mix_is_golds(t, s):
    a = t["lead_cost_attribution"]
    g = s["gold_leads"]
    assert a["leads"].sum() == g["leads"]
    assert a.groupby("attributed_by")["leads"].sum().to_dict() == g["attributed_by"]
    assert a.groupby("came_by")["leads"].sum().to_dict() == g["came_by"]
    assert a["issued_leads"].sum() == g["issued"]
    # leads with a campaign, per client, are the client table's paid leads
    paid = a[a["attributed_by"] != "none"].groupby("client")["leads"].sum()
    assert paid.to_dict() == t["lead_cost_clients"].set_index("client")["paid_leads"].to_dict()
    assert set(a["attributed_by_label"]) == set(ATTRIBUTED_BY.values())


def test_weekly_adds_up_and_marks_the_unfinished_weeks(t):
    w, c = t["lead_cost_weekly"], t["lead_cost_clients"].set_index("client")
    sums = w.groupby("client")[["spend", "paid_leads", "issued_leads", "demos"]].sum()
    for client, r in sums.iterrows():
        assert round(r["spend"], 2) == c.loc[client, "spend"]
        assert (r["paid_leads"], r["issued_leads"], r["demos"]) == \
            tuple(c.loc[client, ["paid_leads", "issued_leads", "demos"]])
    notes = w.drop_duplicates("week").set_index("week")["week_note"]
    assert notes.iloc[0] == "starts mid-week" and notes.iloc[-1] == "two days only"
    assert (notes[notes.index >= DEMOS_INCOMPLETE_FROM].iloc[:-1] == "demos not all in yet").all()
    assert (notes.iloc[1:][notes.index[1:] < DEMOS_INCOMPLETE_FROM] == "").all()
    # the demo rate really drops from that week on: the note is about the data, not a guess
    by_week = w.groupby("week")[["issued_leads", "demos"]].sum()
    done = by_week[(by_week.index < DEMOS_INCOMPLETE_FROM)]
    late = by_week[(by_week.index > DEMOS_INCOMPLETE_FROM)]
    assert (late["demos"] / late["issued_leads"].clip(lower=1)).max() < (done["demos"] / done["issued_leads"]).min()


def test_load_audit_flags_only_the_repeated_file(t, s):
    a, e = t["lead_cost_load_audit"], t["lead_cost_exports"]
    flagged = a[a["status"] != "landed in full"]
    assert flagged["file"].tolist() == ["social_spend_20260514.csv"]
    assert flagged["status"].str.startswith("repeat of batch").all()
    assert e.set_index("source")["files"].to_dict() == {k: v["files"] for k, v in s["exports"].items()}
    assert e.set_index("source")["loaded_rows"].to_dict() == {k: v["rows"] for k, v in s["exports"].items()}
    assert (e["declared_rows"] == e["loaded_rows"]).all() and e["repeated_files"].sum() == 1


def test_faults_table_is_faults_json(t):
    f = t["lead_cost_faults"]
    assert f["caught"].all()
    assert (f["cost_per_issued_lead_without_tests"] - f["cost_per_issued_lead_clean"]).round(2).tolist() == \
        f["moves_by"].tolist()
    assert f.set_index("fault").loc["click_id_case", "moves_by"] == 58.19


def _queries(page: str) -> dict[str, str]:
    return dict(re.findall(r"```sql (\w+)\n(.*?)```", page, flags=re.S))


def _fill(sql: str, client: str = "North Roofing") -> str:
    return sql.replace("${inputs.client.value}", client)


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
        if "${inputs.client.value}" in sql:
            for client in t["lead_cost_clients"]["client_label"]:
                assert site.sql(_fill(sql, client)).fetchall(), (name, client)
        else:
            assert site.sql(sql).fetchall(), name


def test_page_components_use_existing_columns(t, page, site):
    queries = _queries(page)

    def columns(name: str) -> set[str]:
        return {c[0] for c in site.sql(_fill(queries[name])).description}

    for comp in re.findall(r"<(?:BigValue|Value) data=\{(\w+)\}([^>]*)>", page):
        for col in re.findall(r"\b(?:value|column)=(\w+)", comp[1]):
            assert col in columns(comp[0]), col
    for name, attrs in re.findall(r"<(?:BarChart|LineChart|Dropdown) data=\{(\w+)\}(.*?)/?>", page, flags=re.S):
        for col in re.findall(r"\b(?:x|y|value|series)=(\w+)", attrs):
            assert col in columns(name), (name, col)
    for name, body in re.findall(r"<DataTable data=\{(\w+)\}[^>]*>(.*?)</DataTable>", page, flags=re.S):
        for col in re.findall(r"<Column id=(\w+)", body):
            assert col in columns(name), (name, col)
    for name, var, body in re.findall(r"\{#each (\w+) as (\w)\}(.*?)\{/each\}", page, flags=re.S):
        for field in re.findall(rf"\b{var}\.(\w+)", body):
            assert field in columns(name), (name, field)


def test_page_words_match_the_data(page, t, site):
    flat = " ".join(page.split())
    assert 'defaultValue="North Roofing"' in page
    k = t["lead_cost_campaigns"]
    assert k["campaign_id"].nunique() == 11 and "eleven campaigns" in flat
    # "A social lead is cheaper than a search lead, but fewer of them get issued, so the gap shrinks or reverses"
    p = site.sql(_queries(page)["platforms"]).df().set_index("platform")
    assert p.loc["social", "cost_per_lead"] < p.loc["search", "cost_per_lead"]
    assert p.loc["social", "issued_rate"] < p.loc["search", "issued_rate"]
    gap_lead = p.loc["search", "cost_per_lead"] - p.loc["social", "cost_per_lead"]
    gap_issued = p.loc["search", "cost_per_issued_lead"] - p.loc["social", "cost_per_issued_lead"]
    assert gap_issued < gap_lead
    # "3 of the four move the headline by less than two dollars ... the cost per issued lead rises by about a quarter"
    f = t["lead_cost_faults"].set_index("fault")
    assert (f["moves_by"].abs() < 2).sum() == 3
    assert 0.2 < f.loc["click_id_case", "moves_by"] / f.loc["click_id_case", "cost_per_issued_lead_clean"] < 0.3
    assert "the week of 2026-06-15" in flat and DEMOS_INCOMPLETE_FROM == pd.Timestamp("2026-06-15").date()
    assert "phones typed four ways" in flat and "548 files" not in flat  # the file count comes from the data


def test_nightly_smoke_test_opens_the_page():
    assert re.search(r"for page in .* lead-cost/", NIGHTLY.read_text())
