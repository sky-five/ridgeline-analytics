"""A second, independent way to compute every governed metric, month by month.

Each check is plain SQL written straight against the warehouse, without MetricFlow. Where an earlier table
holds the same facts, the check starts there (MRR from the movement ledger instead of the daily MRR mart,
signups from the accounts staging model, spend from the ad-platform rows), so a bug in a mart or in a
measure shows up as a disagreement. Every query returns `month` and `value`.

`{as_of}` is the day the warehouse was built to (last day in fct_mrr_daily).
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Check:
    source: str  # the table the check starts from, shown on the glossary page
    sql: str


_MONTHS = "select cast(date_trunc('month', date_day) as date) as month from fct_mrr_daily group by 1"

# month-end MRR per account, rebuilt from the movement ledger
_LEDGER = f"""
with months as ({_MONTHS}),
balances as (
    select m.month, mv.account_id, sum(mv.mrr_delta) as mrr
    from months m
    join fct_mrr_movements mv on mv.movement_date < m.month + interval 1 month
    group by 1, 2
)"""


def _movement(types: str) -> Check:
    return Check("fct_mrr_movements", f"""
select movement_month as month, sum(mrr_delta) as value
from fct_mrr_movements where movement_type in ({types}) group by 1""")


def _funnel(expr: str) -> Check:
    # the funnel flags rebuilt from their timestamps, not read from the is_* columns
    return Check("fct_account_funnel", f"""
with f as (
    select signup_at,
           proposals_14d > 0 as activated,
           cast(signup_at as date) <= date '{{as_of}}' - interval 60 day as mature,
           coalesce(first_paid_at < signup_at + interval 60 day, false) as paid_60d
    from fct_account_funnel
)
select cast(date_trunc('month', signup_at) as date) as month, {expr} as value from f group by 1""")


def _leads(expr: str) -> Check:
    # outcome groups rebuilt from the raw outcome, from the staging model
    return Check("stg_contractor_ops__leads", f"""
with l as (
    select created_at, outcome,
           floor(date_diff('second', created_at, first_contact_at) / 60.0) as speed_min
    from stg_contractor_ops__leads
)
select cast(date_trunc('month', created_at) as date) as month, {expr} as value from l group by 1""")


def _orders(expr: str) -> Check:
    return Check("stg_app_db__measurement_orders", f"""
select cast(date_trunc('month', ordered_at) as date) as month, {expr} as value
from stg_app_db__measurement_orders group by 1""")


def _cohort(expr: str) -> Check:
    return Check("fct_cohort_retention", f"""
select cohort_month as month, {expr} as value from fct_cohort_retention group by 1""")


_SPEND = "select cast(date_trunc('month', spend_date) as date) as month, sum(spend_usd) as spend " \
         "from stg_ads__ad_spend group by 1"
# paid conversions land on the signup day of the converting accounts, from every channel (organic and
# referral too), so CAC over all channels is blended: paid spend / all paid conversions
_CONVERSIONS = """
select cast(date_trunc('month', a.signup_at) as date) as month,
       count(*) filter (where f.first_paid_at < a.signup_at + interval 60 day) as paid
from stg_app_db__accounts a
left join fct_account_funnel f using (account_id)
group by 1"""

WON = "outcome = 'won'"

CHECKS: dict[str, Check] = {
    # --- revenue: rebuilt from the movement ledger
    "mrr": Check("fct_mrr_movements", f"{_LEDGER}\nselect month, sum(mrr) as value from balances group by 1"),
    "paying_accounts": Check("fct_mrr_movements",
                             f"{_LEDGER}\nselect month, count(*) filter (where mrr > 0) as value "
                             "from balances group by 1"),
    "new_mrr": _movement("'new'"),
    "expansion_mrr": _movement("'expansion'"),
    "churned_mrr": _movement("'churn'"),
    "net_new_mrr": _movement("'new', 'expansion', 'reactivation', 'contraction', 'churn'"),
    # --- growth
    "signups": Check("stg_app_db__accounts", """
select cast(date_trunc('month', signup_at) as date) as month, count(distinct account_id) as value
from stg_app_db__accounts group by 1"""),
    "activated_signups": _funnel("count(*) filter (where activated)"),
    "activation_rate": _funnel("avg(case when activated then 1.0 else 0 end)"),
    "mature_signups": _funnel("count(*) filter (where mature)"),
    "mature_paid_60d": _funnel("count(*) filter (where mature and paid_60d)"),
    "free_to_paid_60d": _funnel("count(*) filter (where mature and paid_60d) / "
                                "nullif(count(*) filter (where mature), 0)"),
    "ad_spend": Check("stg_ads__ad_spend", f"select month, spend as value from ({_SPEND})"),
    "paid_conversions": Check("stg_app_db__accounts", f"select month, paid as value from ({_CONVERSIONS})"),
    "cac": Check("stg_ads__ad_spend", f"""
select s.month, s.spend / nullif(c.paid, 0) as value
from ({_SPEND}) s join ({_CONVERSIONS}) c using (month)"""),
    # --- contractor outcomes
    "leads": _leads("count(*)"),
    "won_leads": _leads(f"count(*) filter (where {WON})"),
    "closed_leads": _leads("count(*) filter (where outcome is not null and outcome <> 'open')"),
    "lead_close_rate": _leads(f"count(*) filter (where {WON}) / "
                              "nullif(count(*) filter (where outcome is not null and outcome <> 'open'), 0)"),
    "speed_to_lead_median_min": _leads("quantile_cont(speed_min, 0.5)"),
    # --- customer experience
    "tickets": Check("stg_support__tickets", """
select cast(date_trunc('month', created_at) as date) as month, count(distinct ticket_id) as value
from stg_support__tickets group by 1"""),
    "measurement_orders": _orders("count(distinct order_id)"),
    "redo_orders": _orders("count(distinct order_id) filter (where redo_requested_at is not null)"),
    "measurement_redo_rate": _orders("count(distinct order_id) filter (where redo_requested_at is not null) / "
                                     "count(distinct order_id)"),
    # --- paid cohorts
    "cohort_start_mrr": _cohort("sum(cohort_start_mrr)"),
    "retained_mrr": _cohort("sum(retained_mrr)"),
    "nrr_12m": _cohort("sum(retained_mrr) filter (where months_since_start = 12) / "
                       "nullif(sum(cohort_start_mrr) filter (where months_since_start = 12), 0)"),
}
