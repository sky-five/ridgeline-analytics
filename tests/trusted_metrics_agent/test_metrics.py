"""Every governed metric equals an independent pandas computation from the raw exports, every role sees exactly
what metrics.yml allows, and pay values for small groups never leave the service."""
import calendar
from datetime import date
from itertools import combinations

import duckdb
import pandas as pd
import pytest
import yaml

from trusted_metrics_agent.hr_data import exports
from trusted_metrics_agent.metrics import CATALOG, SENSITIVE, Catalog, Declined, MetricStore

CAT = Catalog.load()
MONTHS = pd.period_range("2024-01", "2026-09", freq="M")


def month_end(p: pd.Period) -> date:
    return date(p.year, p.month, calendar.monthrange(p.year, p.month)[1])


@pytest.fixture(scope="module")
def ref() -> pd.DataFrame:
    """Company-level reference values per month, computed straight from the exports."""
    e = exports()
    emp = e.employees.merge(e.terminations, on="emp_id", how="left")
    sal = e.salary_changes.sort_values("effective_date")
    pay = e.pay_lines.pivot_table(index="pay_date", columns="pay_type", values="amount_cents", aggfunc="sum")
    out = []
    for p in MONTHS:
        me = month_end(p)
        on = emp[(emp["hire_date"] <= me) & (emp["term_date"].isna() | (emp["term_date"] > me))]
        tenure = [(me.year - h.year) * 12 + me.month - h.month for h in on["hire_date"]]
        base = [sal[(sal["emp_id"] == i) & (sal["effective_date"] <= me)]["annual_base_cents"].iloc[-1]
                for i in on["emp_id"]]
        terms = emp["term_date"].dropna().map(lambda d: pd.Period(d, "M"))
        hires = emp["hire_date"].map(lambda d: pd.Period(d, "M"))
        out.append({
            "month": str(p), "headcount": len(on), "hires": int((hires == p).sum()),
            "terminations": int((terms == p).sum()),
            "voluntary_terminations": int(((terms == p) & (emp.loc[terms.index, "term_reason"] == "voluntary")).sum()),
            "terms_in_window": int(((terms > p - 12) & (terms <= p)).sum()),
            "avg_tenure_months": sum(tenure) / len(on), "avg_base_salary": sum(base) / len(on) / 100,
            "payroll_cost": pay.loc[me].sum() / 100,
            "overtime_share": pay.loc[me, "overtime"] / (pay.loc[me, "base"] + pay.loc[me, "overtime"]),
        })
    df = pd.DataFrame(out).set_index("month")
    avg_hc = df["headcount"].rolling(12).mean()
    df["attrition_rate_12m"] = df["terms_in_window"] / avg_hc
    return df


@pytest.fixture(scope="module")
def hr(db):
    return MetricStore.open("hr_partner", db)


@pytest.mark.parametrize("metric", list(CAT.metrics))
def test_every_metric_matches_the_raw_exports_every_month(hr, ref, metric):
    m = CAT.metrics[metric]
    start = m.first_month or "2024-01"
    got = {r["month"]: r["value"] for r in hr.query_metric(metric, start, "2026-09")["rows"]}
    want = ref.loc[start:, metric]
    assert len(got) == len(want)
    for month, value in want.items():
        assert got[month] == pytest.approx(value, abs=10 ** -{"usd": 2, "share": 4, "months": 1, "people": 0}[m.unit])


def test_groups_add_up_to_the_company_total(hr):
    for metric in ("headcount", "hires", "terminations"):
        total = hr.query_metric(metric, "2026-09")["rows"][0]["value"]
        for dim in ("department", "location", "job_level"):
            rows = hr.query_metric(metric, "2026-09", group_by=[dim])["rows"]
            assert sum(r["value"] for r in rows) == total, (metric, dim)


def test_department_headcount_matches_the_exports(hr):
    e = exports()
    emp = e.employees.merge(e.terminations, on="emp_id", how="left")
    me = date(2026, 9, 30)
    want = emp[(emp["hire_date"] <= me) & (emp["term_date"].isna() | (emp["term_date"] > me))].groupby(
        "department").size().to_dict()
    rows = hr.query_metric("headcount", "2026-09", group_by=["department"])["rows"]
    got = {r["department"]: r["value"] for r in rows}
    assert got == want


# ---- roles

@pytest.mark.parametrize("role", list(CAT.roles))
def test_each_role_sees_exactly_its_metrics(db, role):
    store = MetricStore.open(role, db)
    allowed = CAT.roles[role]["metrics"]
    assert [c["metric"] for c in store.list_metrics()["metrics"]] == allowed
    for metric in CAT.metrics:
        if metric in allowed:
            assert store.query_metric(metric, "2026-09")["rows"]
        else:
            with pytest.raises(Declined, match=f"cannot see {metric}"):
                store.query_metric(metric, "2026-09")
            assert store.describe_metric(metric)["your_role_can_query"] is False


@pytest.mark.parametrize("role", list(CAT.roles))
def test_breakdowns_outside_the_role_are_declined(db, role):
    store = MetricStore.open(role, db)
    for dim in set(CAT.dimensions) - set(CAT.roles[role]["group_by"]):
        with pytest.raises(Declined, match=f"down by {dim}"):
            store.query_metric("headcount", "2026-09", group_by=[dim])
        with pytest.raises(Declined, match=f"down by {dim}"):
            store.query_metric("headcount", "2026-09", filters={dim: store.values[dim][0]})


def test_a_decline_carries_no_values(db, hr):
    salary = hr.query_metric("avg_base_salary", "2026-09")["rows"][0]["value"]
    with pytest.raises(Declined) as e:
        MetricStore.open("people_manager", db).query_metric("avg_base_salary", "2026-09")
    assert str(int(salary)) not in str(e.value) and "hr_partner" in str(e.value)


# ---- small groups

def every_sensitive_query():
    for metric in (m for m, spec in CAT.metrics.items() if spec.sensitivity in SENSITIVE):
        for k in (1, 2, 3):
            for dims in combinations(CAT.dimensions, k):
                yield metric, list(dims)


def test_pay_is_never_shown_for_a_group_under_five_people(db, hr):
    with duckdb.connect(str(db), read_only=True) as con:
        size = {(str(m)[:7], d, loc, lvl): (hc, paid) for m, d, loc, lvl, hc, paid in con.execute(
            "select month_end, department, location, job_level, headcount, paid_employees from hr_group_months"
        ).fetchall()}
    for metric, dims in every_sensitive_query():
        people = CAT.metrics[metric].people
        res = hr.query_metric(metric, "2026-01", "2026-09", group_by=dims)
        by_month = {}
        for r in res["rows"]:
            n = sum(v[0 if people == "headcount" else 1] for k, v in size.items()
                    if k[0] == r["month"] and all(r[d] == k[1 + CAT.dimensions.index(d)] for d in dims))
            if n < CAT.small_group_min:
                assert r["value"] is None and r["withheld"].startswith("fewer than"), (metric, dims, r)
            by_month.setdefault(r["month"], []).append(r)
        for rows in by_month.values():  # never exactly one hidden group next to shown ones
            hidden = sum(r["value"] is None for r in rows)
            assert hidden != 1 or len(rows) == 1, (metric, dims)


def test_a_lone_small_group_takes_the_next_smallest_with_it(hr):
    rows = hr.query_metric("avg_base_salary", "2026-09", group_by=["location"], filters={"department": "Finance"})
    rows = rows["rows"]
    assert sum(r["value"] is None for r in rows) >= 2


def test_internal_metrics_are_not_withheld(hr):
    rows = hr.query_metric("headcount", "2026-09", group_by=["department", "location", "job_level"])["rows"]
    assert all(r["value"] is not None for r in rows) and min(r["value"] for r in rows) < 5


# ---- every answer cites its definition; nothing else gets in

def test_results_cite_the_definition_they_came_from(hr):
    raw = yaml.safe_load(CATALOG.read_text())["metrics"]
    for metric in CAT.metrics:
        res = hr.query_metric(metric, "2026-09")
        assert res["source"] == f"trusted_metrics_agent/metrics.yml#{metric}"
        assert res["definition"] == raw[metric]["definition"] and res["version"] == raw[metric]["version"]
        assert res["model"] == "hr_group_months"


def test_the_connection_is_read_only(hr):
    with pytest.raises(duckdb.Error):
        hr.con.execute("create table x as select 1")


@pytest.mark.parametrize("kwargs, match", [
    ({"metric": "salary", "start_month": "2026-09"}, "not a governed metric"),
    ({"metric": "headcount", "start_month": "2026-9"}, "YYYY-MM"),
    ({"metric": "headcount", "start_month": "2023-12"}, "data from 2024-01 to 2026-09"),
    ({"metric": "attrition_rate_12m", "start_month": "2024-06"}, "data from 2024-12"),
    ({"metric": "headcount", "start_month": "2026-10"}, "to 2026-09"),
    ({"metric": "headcount", "start_month": "2026-09", "end_month": "2026-01"}, "after"),
    ({"metric": "headcount", "start_month": "2026-09", "filters": {"department": "Legal'; drop table x"}},
     "no department"),
    ({"metric": "headcount", "start_month": "2026-09", "group_by": ["emp_id"]}, "unknown dimension"),
])
def test_bad_requests_are_errors_not_queries(hr, kwargs, match):
    with pytest.raises(ValueError, match=match):
        hr.query_metric(**kwargs)


def test_catalog_rejects_roles_that_name_unknown_metrics(tmp_path):
    raw = yaml.safe_load(CATALOG.read_text())
    raw["roles"]["all_staff"]["metrics"].append("bonus_by_person")
    (tmp_path / "m.yml").write_text(yaml.safe_dump(raw))
    with pytest.raises(ValueError, match="bonus_by_person"):
        Catalog.load(tmp_path / "m.yml")


def test_store_refuses_a_catalog_whose_columns_the_model_lacks(db, tmp_path):
    raw = yaml.safe_load(CATALOG.read_text())
    raw["metrics"]["headcount"]["numerator"] = ["contractors"]
    (tmp_path / "m.yml").write_text(yaml.safe_dump(raw))
    with pytest.raises(ValueError, match="contractors"):
        MetricStore.open("all_staff", db, Catalog.load(tmp_path / "m.yml"))
    with pytest.raises(ValueError, match="unknown role"):
        MetricStore.open("admin", db)
