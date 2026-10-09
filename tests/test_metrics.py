"""Governed metrics (MetricFlow) must agree with the marts they're defined on.

Needs a built warehouse: run scripts/run_all.py first. Marked `warehouse`.
"""
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "warehouse" / "ridgeline.duckdb"
pytestmark = [pytest.mark.warehouse, pytest.mark.skipif(not DB.exists(), reason="build the warehouse first")]


def mf_query(tmp_path, metric: str, group_by: str | None = None, where: str | None = None) -> list[dict]:
    from semantic import query

    df = query([metric], [group_by] if group_by else None, [where] if where else None)
    return [{k: (str(v) if k.startswith("metric_time") else v) for k, v in row.items()}
            for row in df.to_dict("records")]


def sql(q):
    with duckdb.connect(str(DB)) as c:  # same config as MetricFlow's in-process connection
        return c.sql(q).fetchall()


def test_mrr_month_end_matches_daily_mart(tmp_path):
    rows = mf_query(tmp_path, "mrr", "metric_time__month")
    got = {r["metric_time__month"][:10]: float(r["mrr"]) for r in rows}
    want = dict(sql("select strftime(date_trunc('month', date_day), '%Y-%m-%d'), "
                    "arg_max(mrr, date_day)::double from fct_mrr_daily group by 1"))
    assert got and got == pytest.approx(want)


def test_free_to_paid_matches_funnel(tmp_path):
    got = float(mf_query(tmp_path, "free_to_paid_60d")[0]["free_to_paid_60d"])
    want = sql("select avg(case when is_paid_60d then 1.0 else 0 end) from fct_account_funnel where is_mature")[0][0]
    assert got == pytest.approx(float(want))


def test_lead_close_rate_matches_leads(tmp_path):
    got = float(mf_query(tmp_path, "lead_close_rate")[0]["lead_close_rate"])
    want = sql("select sum(case when outcome_group='won' then 1.0 else 0 end) / "
               "sum(case when outcome_group <> 'open' then 1 else 0 end) from fct_contractor_leads")[0][0]
    assert got == pytest.approx(float(want))


def test_net_new_mrr_sums_movements(tmp_path):
    rows = mf_query(tmp_path, "net_new_mrr", "metric_time__year")
    got = sum(float(r["net_new_mrr"]) for r in rows)
    want = sql("select sum(mrr_delta) from fct_mrr_movements")[0][0]
    assert got == pytest.approx(float(want))


def test_reporting_export_uses_governed_metrics():
    # Dashboards read reporting.* tables; they must hold the semantic layer's numbers, not re-derived ones.
    from scripts.export_reporting import export

    export(DB)
    got = dict(sql("select strftime(month, '%Y-%m-%d'), mrr from reporting.kpi_monthly"))
    want = dict(sql("select strftime(date_trunc('month', date_day), '%Y-%m-%d'), "
                    "arg_max(mrr, date_day)::double from fct_mrr_daily group by 1"))
    assert got and got == pytest.approx(want)
    names = {r[0] for r in sql("select name from reporting.metric_catalog")}
    assert {"mrr", "free_to_paid_60d", "lead_close_rate", "nrr_12m"} <= names
