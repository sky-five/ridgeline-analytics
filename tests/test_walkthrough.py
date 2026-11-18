"""WALKTHROUGH.md follows one number (MRR on 2026-06-30) from the source to the dashboard. Keep it true.

The first tests need no warehouse: links resolve, and the quoted figures match the simulator and the metric
contract. The last test needs a warehouse built as of 2026-06-30 (the metric-contract CI job builds one) and
checks every stage gives the same number; on any other date it is skipped.
"""
import json
import re
from datetime import date
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "WALKTHROUGH.md"
DB = ROOT / "warehouse" / "ridgeline.duckdb"
AS_OF = "2026-06-30"
MRR, ACTIVE, SUBSCRIPTIONS, CANCELED, CHANGES = 214_743, 683, 1_248, 565, 2_789


@pytest.fixture(scope="module")
def text():
    return DOC.read_text(encoding="utf-8")


def test_every_relative_link_exists(text):
    links = [t for t in re.findall(r"\]\(([^)\s]+)\)", text) if not t.startswith(("http://", "https://", "#"))]
    assert len(links) > 15
    missing = [t for t in links if not (ROOT / t.split("#")[0]).exists()]
    assert not missing


def test_backticked_paths_exist(text):
    paths = [p for p in re.findall(r"`([\w./-]+/[\w./-]*)`", text) if not p.startswith("raw_")]
    assert paths
    assert [p for p in paths if not (ROOT / p).exists()] == []


def test_models_and_tests_named_exist(text):
    for model in re.findall(r"`((?:stg|int|fct)_[a-z_]+)`", text):
        assert list((ROOT / "dbt" / "models").rglob(f"{model}.sql")), model
    finance_yml = (ROOT / "dbt/models/marts/finance/_finance_models.yml").read_text()
    for unit in ("mrr_movements_types", "mrr_movements_month_boundary"):
        assert unit in text and f"name: {unit}" in finance_yml


def test_quoted_figures(text):
    assert f"${MRR:,}" in text and f"{ACTIVE} active" in text
    assert f"{SUBSCRIPTIONS:,} rows" in text and f"{CANCELED} canceled" in text and f"{CHANGES:,} rows" in text


def test_figures_match_metric_contract(text):
    contract = json.loads((ROOT / "metric_contract" / "contract.json").read_text())
    assert contract["snapshot_as_of"] == AS_OF and AS_OF in text
    assert contract["metrics"]["mrr"]["values"]["2026-06"] == MRR
    assert contract["metrics"]["paying_accounts"]["values"]["2026-06"] == ACTIVE
    assert f"`mrr`, version {contract['metrics']['mrr']['version']}" in text


def test_figures_match_the_simulator():
    from pipelines import engine

    world = engine.world_as_of(date(2026, 6, 30))
    subs = world["subscriptions"]
    assert len(subs) == SUBSCRIPTIONS and len(world["subscription_changes"]) == CHANGES
    active = subs[subs.status == "active"]
    assert len(active) == ACTIVE and active.mrr_usd.sum() == MRR
    assert (subs.status == "canceled").sum() == CANCELED and subs[subs.status == "canceled"].mrr_usd.sum() == 0


def _built_as_of() -> str | None:
    marker = DB.with_name(DB.name + ".as_of")
    return marker.read_text().strip() if marker.exists() else None


@pytest.mark.warehouse
@pytest.mark.skipif(_built_as_of() != AS_OF, reason=f"needs a warehouse built as of {AS_OF}")
def test_every_stage_gives_the_same_number():
    with duckdb.connect(str(DB)) as c:  # same config as MetricFlow's in-process connection
        raw = c.sql("select count(*), sum(mrr_usd) from raw_app_db.subscriptions where status = 'active'").fetchone()
        mart = c.sql(f"select mrr from fct_mrr_daily where date_day = '{AS_OF}'").fetchone()
        report = c.sql("select mrr, paying_accounts from reporting.kpi_monthly "
                       "where month = '2026-06-01'").fetchone()
    assert raw == (ACTIVE, MRR)
    assert float(mart[0]) == MRR
    assert (float(report[0]), float(report[1])) == (MRR, ACTIVE)

    from semantic import query

    df = query(["mrr", "paying_accounts"], ["metric_time__month"])
    june = df[df.metric_time__month.astype(str).str.startswith("2026-06")].iloc[0]
    assert (float(june.mrr), float(june.paying_accounts)) == (MRR, ACTIVE)
