"""The tools on the real warehouse: governed metrics come back through the guard and match the marts."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "warehouse" / "ridgeline.duckdb"
pytestmark = [pytest.mark.warehouse, pytest.mark.skipif(not DB.exists(), reason="build the warehouse first")]


def test_query_metric_matches_the_mart():
    from analyst import tools

    got = tools.query_metric(["mrr"], ["metric_time__month"], order_by=["-metric_time__month"], limit=1)
    assert "error" not in got, got
    assert got["compiled_sql"].lstrip().startswith(("--", "SELECT"))
    want = tools.run_sql("select mrr from fct_mrr_daily order by date_day desc limit 1")["rows"][0][0]
    assert got["rows"][0][1] == pytest.approx(want)


def test_bad_calls_return_errors_the_agent_can_read():
    from analyst import tools

    assert "error" in tools.query_metric(["no_such_metric"])
    assert "error" in tools.run_sql("select nope from fct_mrr_daily")
    assert "only SELECT" in tools.run_sql("delete from fct_mrr_daily")["error"]
    assert "did you mean" in tools.describe_model("mrr_daily")["error"]


def test_catalog_on_the_real_manifest():
    from analyst import tools

    sources = {n["name"] for n in tools.get_lineage("fct_mrr_daily")["nodes"] if n["layer"] == "source"}
    assert sources and all("." in s for s in sources)
    assert {m["name"] for m in tools.list_metrics()["metrics"]} >= {"mrr", "lead_close_rate", "nrr_12m"}
    assert tools.search_catalog("lead close rate")["results"][0]["name"] in ("lead_close_rate", "fct_contractor_leads")
