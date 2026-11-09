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


def test_reporting_export_carries_the_health_results():
    # the Renewals at risk page reads the committed customer_health results through reporting.*
    import json

    from scripts.export_reporting import ROOT, export

    export(DB)
    results = ROOT / "customer_health" / "results"
    n_csv = sum(1 for _ in (results / "at_risk.csv").open()) - 1
    assert sql("select count(*) from reporting.health_at_risk")[0][0] == n_csv
    summary = json.loads((results / "summary.json").read_text())
    aucs = dict(sql("select method, auc from reporting.health_compare"))
    assert sorted(aucs.values()) == sorted([summary["auc_health_score"], summary["auc_model"]])


def test_account_reviews_match_the_marts():
    # every review page reads reporting.account_review*; its MRR must reconcile with the finance marts
    from scripts.export_reporting import export

    export(DB)
    assert sql("select count(*) from reporting.account_review")[0][0] == 25
    assert sql("select count(*) from reporting.account_review_monthly")[0][0] == 25 * 12
    # the reviewed accounts are the largest by current MRR
    smallest_reviewed = sql("select min(mrr) from reporting.account_review")[0][0]
    assert sql(f"select count(*) from fct_account_health where mrr > {smallest_reviewed}")[0][0] < 25
    # month-end MRR on the review = that account's MRR movements summed up to the end of the month
    got = {(a, str(m)): float(v) for a, m, v in sql(
        "select account_id, month, mrr from reporting.account_review_monthly")}
    want = {(a, str(m)): float(v) for a, m, v in sql("""
        select r.account_id, r.month, coalesce(sum(mv.mrr_delta), 0)
        from reporting.account_review_monthly r
        left join fct_mrr_movements mv
          on mv.account_id = r.account_id and mv.changed_at < r.month + interval 1 month
        group by 1, 2""")}
    assert got == pytest.approx(want)
    # monthly tickets on the review = the support mart counted directly
    got_t = dict(sql("select account_id, sum(tickets) from reporting.account_review_monthly group by 1"))
    want_t = dict(sql("""
        select r.account_id, count(t.ticket_id)
        from reporting.account_review r
        left join fct_support_tickets t on t.account_id = r.account_id
          and t.created_at >= (select min(month) from reporting.account_review_monthly)
          and t.created_at < (select max(month) from reporting.account_review_monthly) + interval 1 month
        group by 1"""))
    assert got_t == want_t
