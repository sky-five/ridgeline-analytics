from datetime import date

import pytest

from revrec.billing import Billing, Subscription, from_engine
from revrec.build import build

ITEMS = ["new_part_month_cents", "ended_part_month_cents", "price_change_part_month_cents",
         "calendar_and_rounding_cents"]


def _definitions(con) -> dict[date, dict[str, int]]:
    cur = con.execute("select * from fct_arr_definitions order by month_start")
    cols = [c[0] for c in cur.description]
    return {r[0]: dict(zip(cols[1:], r[1:], strict=True)) for r in cur.fetchall()}


def test_annual_plan_shows_the_prepay_discount_and_the_calendar_effect():
    # $400/month list, billed $4,000 a year up front for 365 days from 1 Jan.
    b = Billing()
    s = Subscription("sub_1", "cus_1", "team", 10, "year")
    b.change(s, date(2025, 1, 1), 40_000, "new")
    b.line(s, "subscription", date(2025, 1, 1), date(2025, 1, 1), date(2026, 1, 1), 400_000)
    d = _definitions(build(b, as_of=date(2025, 2, 28)))

    jan, feb = d[date(2025, 1, 1)], d[date(2025, 2, 1)]
    assert jan["contract_arr_cents"] == 480_000
    assert jan["annual_discount_cents"] == -80_000
    assert jan["billed_arr_cents"] == 400_000
    assert jan["run_rate_arr_cents"] == 12 * (400_000 * 31 // 365)  # 33,972 earned in January
    assert jan["calendar_and_rounding_cents"] == 407_664 - 400_000  # a 31-day month runs above 1/12
    assert feb["calendar_and_rounding_cents"] < 0  # a 28-day month runs below


def test_mid_month_start_is_a_part_month_new_item():
    # Monthly plan starting 11 March: 21 of 31 days earned in March.
    b = Billing()
    s = Subscription("sub_1", "cus_1", "starter", 2, "month")
    b.change(s, date(2025, 3, 11), 3_100, "new")
    b.line(s, "subscription", date(2025, 3, 11), date(2025, 3, 11), date(2025, 4, 11), 3_100)
    mar = _definitions(build(b, as_of=date(2025, 3, 31)))[date(2025, 3, 1)]
    assert mar["billed_arr_cents"] == 37_200
    assert mar["run_rate_arr_cents"] == 12 * 2_100
    assert mar["new_part_month_cents"] == 25_200 - 37_200
    assert mar["calendar_and_rounding_cents"] == 0


def test_churned_customer_still_earns_in_the_month_service_stops():
    # Paid 15 May to 15 June, churns at renewal: no ARR at the end of June, but half of June is revenue.
    b = Billing()
    s = Subscription("sub_1", "cus_1", "team", 1, "month")
    b.change(s, date(2025, 5, 15), 3_100, "new")
    b.change(s, date(2025, 6, 15), 0, "churn")
    b.line(s, "subscription", date(2025, 5, 15), date(2025, 5, 15), date(2025, 6, 15), 3_100)
    jun = _definitions(build(b, as_of=date(2025, 6, 30)))[date(2025, 6, 1)]
    assert jun["contract_arr_cents"] == jun["billed_arr_cents"] == 0
    assert jun["ended_part_month_cents"] == jun["run_rate_arr_cents"] == 12 * 1_400  # 14 of 31 days


def test_mid_month_upgrade_is_a_price_change_item():
    # Monthly plan renewing on the 1st, upgraded on 21 April with a prorated charge.
    b = Billing()
    s = Subscription("sub_1", "cus_1", "starter", 1, "month")
    b.change(s, date(2025, 4, 1), 3_000, "new")
    b.line(s, "subscription", date(2025, 4, 1), date(2025, 4, 1), date(2025, 5, 1), 3_000)
    b.change(s, date(2025, 4, 21), 6_000, "upgrade")
    b.line(s, "proration", date(2025, 4, 21), date(2025, 4, 21), date(2025, 5, 1), 1_000)
    b.change(s, date(2025, 5, 1), 6_000, "seats_up")  # on the 1st: a whole month, not a part month
    b.line(s, "subscription", date(2025, 5, 1), date(2025, 5, 1), date(2025, 6, 1), 6_000)
    d = _definitions(build(b, as_of=date(2025, 5, 31)))
    apr, may = d[date(2025, 4, 1)], d[date(2025, 5, 1)]
    assert apr["billed_arr_cents"] == 72_000 and apr["run_rate_arr_cents"] == 48_000
    assert apr["new_part_month_cents"] == 0
    assert apr["price_change_part_month_cents"] == -24_000
    assert may["run_rate_arr_cents"] == may["billed_arr_cents"] == 72_000
    assert all(may[i] == 0 for i in ITEMS)


def test_mid_month_seat_decrease_is_a_positive_price_change_item():
    # Monthly plan renewing on the 15th, dropping from $60 to $30 at the 15 April renewal. April earned
    # 14 of 31 days at the old price and 16 of 30 at the new one, so it runs above 12 x the new price.
    b = Billing()
    s = Subscription("sub_1", "cus_1", "starter", 4, "month")
    b.change(s, date(2025, 3, 15), 6_000, "new")
    b.line(s, "subscription", date(2025, 3, 15), date(2025, 3, 15), date(2025, 4, 15), 6_000)
    b.change(s, date(2025, 4, 15), 3_000, "seats_down")
    b.line(s, "subscription", date(2025, 4, 15), date(2025, 4, 15), date(2025, 5, 15), 3_000)
    apr = _definitions(build(b, as_of=date(2025, 4, 30)))[date(2025, 4, 1)]
    assert apr["billed_arr_cents"] == 36_000
    assert apr["run_rate_arr_cents"] == 12 * (2_710 + 1_600)
    assert apr["price_change_part_month_cents"] == 15_720


@pytest.fixture(scope="module")
def generated_con():
    return build(from_engine())


def test_bridge_closes_and_ties_to_the_other_models(generated_con):
    rows = generated_con.execute(
        "select d.*, b.closing_arr_cents, 12 * r.recognized_cents from fct_arr_definitions as d "
        "inner join fct_arr_bridge as b using (month_start) "
        "inner join fct_revenue_monthly as r using (month_start)"
    ).fetchall()
    cols = [c[0] for c in generated_con.execute("select * from fct_arr_definitions limit 0").description]
    assert len(rows) == generated_con.execute("select count(*) from fct_arr_definitions").fetchone()[0] == 21
    for r in rows:
        d = dict(zip(cols, r, strict=False))
        assert d["contract_arr_cents"] == r[-2]  # same ARR as the movement bridge
        assert d["run_rate_arr_cents"] == r[-1]  # same revenue as the revenue schedule
        assert d["contract_arr_cents"] + d["annual_discount_cents"] == d["billed_arr_cents"]
        assert d["billed_arr_cents"] + sum(d[i] for i in ITEMS) == d["run_rate_arr_cents"]


def test_annual_price_rule_matches_every_annual_invoice(generated_con):
    # Billed ARR assumes annual plans pay 10 x MRR; check that against what was actually invoiced.
    total, wrong = generated_con.execute(
        "select count(*), count(*) filter (where l.amount_cents <> 10 * c.mrr_cents) "
        "from invoice_lines as l inner join sub_billing_interval as i using (subscription_id) "
        "asof inner join subscription_changes as c "
        "on l.subscription_id = c.subscription_id and l.period_start >= c.effective_on "
        "where l.kind = 'subscription' and i.months_per_period = 12"
    ).fetchone()
    assert total > 100
    assert wrong == 0


def test_bridge_items_have_the_expected_signs(generated_con):
    d = _definitions(generated_con)
    months = [m for m in d if m >= date(2025, 3, 1)]  # skip the ramp-up months
    assert all(d[m]["annual_discount_cents"] < 0 for m in months)
    assert all(d[m]["new_part_month_cents"] < 0 for m in months)
    assert all(d[m]["ended_part_month_cents"] >= 0 for m in months)
    # Upgrades and seat increases make the price-change item negative, seat decreases make it positive.
    # Increases outnumber decreases, so the item nets negative once there are enough subscriptions; in
    # March and April 2025 (40 and 55 live subscriptions) one large seat decrease outweighs them.
    assert all(d[m]["price_change_part_month_cents"] <= 0 for m in months if m >= date(2025, 5, 1))
    assert sum(d[m]["price_change_part_month_cents"] for m in months) < 0
    # Ratable by day: 31-day months run above billed ARR, 30-day months below.
    assert all(d[m]["calendar_and_rounding_cents"] > 0 for m in months if m.month in (1, 3, 5, 7, 8, 10, 12))
    assert all(d[m]["calendar_and_rounding_cents"] < 0 for m in months if m.month in (2, 4, 6, 9, 11))


def test_every_mid_month_decrease_is_a_non_negative_item(generated_con):
    # A subscription whose MRR went down mid-month earned the higher price for the first part of it.
    total, wrong = generated_con.execute(
        "select count(*), count(*) filter (where s.run_rate_arr_cents < s.billed_arr_cents) "
        "from arr_sub_months as s asof inner join subscription_changes as c "
        "on s.subscription_id = c.subscription_id and s.month_start >= c.effective_on "
        "where s.bridge_item = 'price_change_part_month' and s.contract_arr_cents < 12 * c.mrr_cents"
    ).fetchone()
    assert total > 30
    assert wrong == 0
