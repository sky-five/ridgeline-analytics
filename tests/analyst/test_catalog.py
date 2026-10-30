"""The catalog reads dbt's manifest: search, describe, lineage, metrics. Uses a tiny fake manifest."""
import pytest

from analyst.catalog import Catalog

SRC = "source.ridgeline.app_db.subscriptions"
STG = "model.ridgeline.stg_subscriptions"
INT = "model.ridgeline.int_mrr_movements"
FCT = "model.ridgeline.fct_mrr_daily"


def model(name, folder, desc="", columns=None, contract=False):
    return {"resource_type": "model", "name": name, "description": desc,
            "original_file_path": f"models/{folder}/{name}.sql", "relation_name": f'"w"."main"."{name}"',
            "config": {"materialized": "table", "contract": {"enforced": contract}},
            "columns": {c: {"description": d, "data_type": "double"} for c, d in (columns or {}).items()}}


@pytest.fixture()
def cat():
    manifest = {
        "nodes": {
            STG: model("stg_subscriptions", "staging", "One row per subscription."),
            INT: model("int_mrr_movements", "intermediate", "MRR changes."),
            FCT: model("fct_mrr_daily", "marts/finance", "Company MRR and paying accounts every day.",
                       {"date_day": "Day", "mrr": "Monthly recurring revenue at end of day"}, contract=True),
            "test.ridgeline.unique_fct": {"resource_type": "test", "name": "unique_fct_mrr_daily_date_day",
                                          "attached_node": FCT, "column_name": "date_day",
                                          "test_metadata": {"name": "unique"}},
        },
        "sources": {SRC: {"resource_type": "source", "name": "subscriptions", "source_name": "app_db"}},
        "unit_tests": {"u1": {"name": "mrr_month_boundaries", "depends_on": {"nodes": [FCT]}}},
        "parent_map": {FCT: [INT], INT: [STG], STG: [SRC], SRC: []},
        "child_map": {SRC: [STG], STG: [INT], INT: [FCT], FCT: []},
    }
    semantic = {
        "semantic_models": [{"name": "mrr_daily", "node_relation": {"alias": "fct_mrr_daily"},
                             "measures": [{"name": "mrr_level"}]}],
        "metrics": [{"name": "mrr", "label": "MRR", "type": "simple",
                     "description": "Monthly recurring revenue at the end of the period.",
                     "type_params": {"measure": {"name": "mrr_level"}}}],
    }
    return Catalog(manifest, semantic)


def test_describe_has_columns_tests_contract_and_neighbours(cat):
    d = cat.describe("FCT_MRR_DAILY")
    assert d["layer"] == "marts" and d["contract_enforced"]
    assert [c["name"] for c in d["columns"]] == ["date_day", "mrr"]
    assert d["tests"] == ["unique(date_day)", "unit:mrr_month_boundaries"]
    assert d["upstream"] == ["int_mrr_movements"] and d["downstream"] == []


def test_lineage_walks_to_the_source_with_hops(cat):
    assert cat.lineage("fct_mrr_daily") == [
        {"name": "int_mrr_movements", "layer": "intermediate", "hops": 1},
        {"name": "stg_subscriptions", "layer": "staging", "hops": 2},
        {"name": "app_db.subscriptions", "layer": "source", "hops": 3},
    ]
    assert [n["name"] for n in cat.lineage("app_db.subscriptions", "downstream", depth=2)] == \
        ["stg_subscriptions", "int_mrr_movements"]


def test_search_prefers_marts_and_finds_metrics(cat):
    hits = cat.search("monthly recurring revenue")
    assert hits[0]["name"] in ("fct_mrr_daily", "mrr")
    assert {"fct_mrr_daily", "mrr"} <= {h["name"] for h in hits}
    assert cat.search("a") == []


def test_metrics_name_the_model_they_are_built_on(cat):
    assert cat.metrics() == [{"name": "mrr", "label": "MRR", "type": "simple",
                              "description": "Monthly recurring revenue at the end of the period.",
                              "built_on": ["fct_mrr_daily"]}]


def test_unknown_names_suggest_close_ones(cat):
    with pytest.raises(KeyError, match="did you mean fct_mrr_daily"):
        cat.describe("mrr_daily")
    with pytest.raises(ValueError):
        cat.lineage("fct_mrr_daily", "sideways")
