"""The claims self-service dashboard tables: they come from the committed semantic-layer answers, the drill-down
table sums back to MetricFlow's own numbers for every slice, and the page reads only tables (and columns) the
export writes."""
import json
import re

import pandas as pd
import pytest

from claims_self_service.report import CUBE, NOT_FIT_FOR, SUMMARY, ratios, tables
from claims_self_service.run import CUBE_METRICS

ROOT = SUMMARY.parents[2]
PAGE = ROOT / "reports" / "pages" / "claims-self-service.md"
HANDOVER = SUMMARY.parents[1] / "HANDOVER.md"
NIGHTLY = ROOT / ".github" / "workflows" / "nightly.yml"
EXPORT = ROOT / "scripts" / "export_reporting.py"
SOURCES = ROOT / "reports" / "sources" / "ridgeline"


@pytest.fixture(scope="module")
def t():
    return tables()


@pytest.fixture(scope="module")
def s():
    return json.loads(SUMMARY.read_text(encoding="utf-8"))


def test_export_writes_six_tables(t):
    assert set(t) == {"claims_ss_summary", "claims_ss_cube", "claims_ss_slices", "claims_ss_hail",
                      "claims_ss_channel_quarterly", "claims_ss_metrics"}
    assert len(t["claims_ss_summary"]) == 1
    assert len(t["claims_ss_slices"]) == 3 + 4 + 3
    assert len(t["claims_ss_hail"]) == 18
    assert len(t["claims_ss_metrics"]) == 12
    assert "claims_ss_tables()" in EXPORT.read_text()
    for name in t:
        assert (SOURCES / f"{name}.sql").read_text().strip() == f"select * from reporting.{name}"


def test_cube_sums_to_the_whole_book(t, s):
    cube = t["claims_ss_cube"]
    assert not cube.duplicated(["month", "line_of_business", "region", "channel"]).any()
    whole = ratios(cube[CUBE_METRICS].sum().to_frame().T).iloc[0]
    for m in ("loss_ratio", "claim_cycle_time_days", "approval_rate"):
        assert whole[m] == pytest.approx(s["headline"][m], abs=1e-4)
    assert cube["earned_premium"].sum() == pytest.approx(s["headline"]["earned_premium"], abs=1)
    assert cube["claims_reported"].sum() == s["claims"] == 2203
    st = s["claims_by_status"]
    assert cube["closed_claims"].sum() == st["approved"] + st["denied"] + st["withdrawn"]
    assert cube["approved_claims"].sum() == st["approved"]
    assert cube["decided_claims"].sum() == st["approved"] + st["denied"]


@pytest.mark.parametrize("dim", ["line_of_business", "region", "channel"])
def test_drill_down_matches_metricflow_for_every_slice(t, s, dim):
    """Summing the additive metrics over a slice and dividing gives MetricFlow's answer for that slice."""
    got = t["claims_ss_cube"].groupby(dim)[CUBE_METRICS].sum()
    got = ratios(got).set_index(got.index)
    for row in s["by"][dim]:
        for m in ("loss_ratio", "claim_cycle_time_days", "approval_rate"):
            assert got.loc[row[dim], m] == pytest.approx(row[m], abs=1e-4), (dim, row[dim], m)


def test_drill_down_matches_metricflow_by_month(t, s):
    cube = t["claims_ss_cube"].assign(month=lambda d: pd.to_datetime(d["month"]).dt.strftime("%Y-%m"))
    got = cube.groupby("month")[CUBE_METRICS].sum()
    got = ratios(got).set_index(got.index)
    for row in s["monthly"]:
        for m in ("loss_ratio", "claim_cycle_time_days", "approval_rate"):
            if m in row:
                assert got.loc[row["month"], m] == pytest.approx(row[m], abs=1e-4), (row["month"], m)


def test_the_hail_month_and_the_direct_channel(t):
    summ = t["claims_ss_summary"].iloc[0]
    assert (summ["hail_region"], summ["hail_month"]) == ("South", "2025-07")
    assert round(summ["hail_loss_ratio"], 1) == 9.4
    assert (summ["hail_claims"], summ["other_months_min_claims"], summ["other_months_max_claims"]) == (82, 0, 17)
    hail = t["claims_ss_hail"]
    assert hail["is_hail_month"].sum() == 1
    assert hail.loc[hail["is_hail_month"], "claims_reported"].item() == hail["claims_reported"].max()

    # the same storm, from the drill-down table the page filters
    cube = t["claims_ss_cube"]
    pick = cube[(cube["line_of_business"] == "homeowners") & (cube["region"] == "south")]
    july = pick[pd.to_datetime(pick["month"]).dt.strftime("%Y-%m") == "2025-07"]
    assert july["claims_reported"].sum() == 82
    july_ratio = july["incurred_losses"].sum() / july["earned_premium"].sum()
    assert july_ratio == pytest.approx(summ["hail_loss_ratio"], abs=1e-4)

    # the page says the direct channel has the highest denial rate in every quarter
    q = t["claims_ss_channel_quarterly"].pivot(index="quarter", columns="channel", values="denial_rate")
    assert (q.idxmax(axis=1) == "direct").all()
    assert q.index.tolist() == ["2025Q1", "2025Q2", "2025Q3", "2025Q4", "2026Q1", "2026Q2"]
    assert round(summ["direct_approval_rate"], 3) == 0.803 and round(summ["agent_approval_rate"], 3) == 0.903


def test_metric_list_comes_from_the_semantic_layer(t, s):
    m = t["claims_ss_metrics"].set_index("name")
    assert sorted(m.index) == sorted(s["metrics"])
    assert m.loc["loss_ratio", "computed_as"] == "incurred_losses / earned_premium"
    assert m.loc["earned_premium", "computed_as"] == "sum of earned_premium_amount"
    assert set(m.index[m["not_fit_for"] != ""]) == set(NOT_FIT_FOR) == {"loss_ratio", "claim_cycle_time_days",
                                                                         "approval_rate"}


def test_page_reads_only_exported_tables_and_columns(t):
    page = PAGE.read_text(encoding="utf-8")
    used = set(re.findall(r"ridgeline\.(\w+)", page))
    assert used == set(t)
    # columns named in components on top-level queries: each must exist in its table
    queries = dict(re.findall(r"```sql (\w+)\nselect \* from ridgeline\.(\w+)", page))
    for name, table in queries.items():
        cols = set(t[table].columns)
        for comp in re.findall(rf"<\w+ data={{{name}}}[^>]*>", page):
            for attr in ("value", "column", "x", "y"):
                for col in re.findall(rf"\b{attr}=(\w+)", comp):
                    assert col in cols, (name, attr, col)
    cube_cols = set(t["claims_ss_cube"].columns)
    for col in re.findall(r"sum\((\w+)\)", page):
        assert col in cube_cols, col


def test_nightly_smoke_test_opens_the_page():
    assert re.search(r"for page in .* claims-self-service/", NIGHTLY.read_text())


def test_handover_covers_query_add_and_limits():
    doc = HANDOVER.read_text(encoding="utf-8")
    for heading in ("## Query a metric", "## Add a metric", "## What each metric is not fit for"):
        assert heading in doc
    for name in NOT_FIT_FOR:
        assert f"`{name}`" in doc
    assert "python -m claims_self_service" in doc and "mf query" in doc


def test_committed_results_exist():
    assert SUMMARY.exists() and CUBE.exists()
