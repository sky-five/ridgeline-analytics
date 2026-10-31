from datetime import date

import pytest

from revrec.billing import Billing, Subscription, generate
from revrec.build import build

SUB = Subscription("sub_1", "cus_1", "team", 1, "year")


def _line(b: Billing, kind: str, start: date, end: date, amount: int, sub: Subscription = SUB) -> None:
    b.line(sub, kind, start, start, end, amount)


def _monthly(con) -> dict[date, int]:
    return dict(con.execute("select month_start, recognized_cents from fct_revenue_monthly").fetchall())


def test_annual_prepay_is_earned_by_day_and_adds_back_exactly():
    b = Billing()
    _line(b, "subscription", date(2025, 1, 15), date(2026, 1, 15), 120_000)  # 365 days
    b.change(SUB, date(2025, 1, 15), 10_000, "new")
    rev = _monthly(build(b, as_of=date(2025, 12, 31)))
    assert rev[date(2025, 1, 1)] == 120_000 * 17 // 365
    assert rev[date(2025, 2, 1)] == 120_000 * 45 // 365 - 120_000 * 17 // 365
    assert rev[date(2026, 1, 1)] == 120_000 - 120_000 * 351 // 365
    assert sum(rev.values()) == 120_000


def test_credit_reverses_the_unearned_rest_of_the_period():
    b = Billing()
    _line(b, "subscription", date(2025, 3, 1), date(2025, 4, 1), 3_100)
    _line(b, "credit", date(2025, 3, 21), date(2025, 4, 1), -1_100)
    rev = _monthly(build(b, as_of=date(2025, 3, 31)))
    assert rev == {date(2025, 3, 1): 2_000}  # 20 of 31 days kept


def test_deferred_rollforward_for_an_annual_prepay():
    b = Billing()
    _line(b, "subscription", date(2025, 1, 15), date(2026, 1, 15), 120_000)
    b.change(SUB, date(2025, 1, 15), 10_000, "new")
    con = build(b, as_of=date(2025, 2, 28))
    rows = con.execute(
        "select opening_cents, billed_cents, recognized_cents, closing_cents from fct_deferred_revenue "
        "order by month_start"
    ).fetchall()
    jan, feb = rows
    assert jan == (0, 120_000, 5_589, 114_411)
    assert feb[0] == jan[3] and feb[1] == 0 and feb[0] - feb[2] == feb[3]


@pytest.fixture
def lifecycle_con():
    """One customer: new, expansion, contraction, churn, then back on a new subscription."""
    b = Billing()
    s1 = Subscription("sub_1", "cus_1", "team", 2, "month")
    s2 = Subscription("sub_2", "cus_1", "starter", 1, "month")
    b.change(s1, date(2025, 1, 10), 8_000, "new")
    b.change(s1, date(2025, 2, 10), 12_000, "seats_up")
    b.change(s1, date(2025, 3, 10), 4_000, "seats_down")
    b.change(s1, date(2025, 4, 10), 0, "churn")
    b.change(s2, date(2025, 6, 3), 1_500, "new")
    _line(b, "subscription", date(2025, 1, 10), date(2025, 2, 10), 8_000, s1)
    return build(b, as_of=date(2025, 6, 30))


def test_arr_movements_per_customer(lifecycle_con):
    moves = lifecycle_con.execute(
        "select month_start, movement, change_mrr_cents from fct_arr_movements order by month_start"
    ).fetchall()
    assert moves == [
        (date(2025, 1, 1), "new", 8_000),
        (date(2025, 2, 1), "expansion", 4_000),
        (date(2025, 3, 1), "contraction", -8_000),
        (date(2025, 4, 1), "churn", -4_000),
        (date(2025, 6, 1), "reactivation", 1_500),
    ]


def test_churn_counts_in_the_month_service_stops():
    # Paid through Apr 30, churn effective May 1: still ARR at the end of April.
    b = Billing()
    s = Subscription("sub_1", "cus_1", "team", 1, "month")
    b.change(s, date(2025, 4, 1), 4_000, "new")
    b.change(s, date(2025, 5, 1), 0, "churn")
    _line(b, "subscription", date(2025, 4, 1), date(2025, 5, 1), 4_000, s)
    con = build(b, as_of=date(2025, 5, 31))
    assert con.execute("select month_start, movement from fct_arr_movements order by 1").fetchall() == [
        (date(2025, 4, 1), "new"),
        (date(2025, 5, 1), "churn"),
    ]


def test_bridge_and_rollforward_identities_on_generated_data():
    con = build(generate())
    bad_bridge = con.execute(
        "select count(*) from fct_arr_bridge where opening_arr_cents + new_cents + reactivation_cents "
        "+ expansion_cents + contraction_cents + churn_cents <> closing_arr_cents"
    ).fetchone()[0]
    bad_deferred = con.execute(
        "select count(*) from fct_deferred_revenue where opening_cents + billed_cents - recognized_cents "
        "<> closing_cents or closing_cents < 0"
    ).fetchone()[0]
    total_billed, total_recognized = con.execute(
        "select (select sum(amount_cents) from invoice_lines), (select sum(recognized_cents) from rev_line_months)"
    ).fetchone()
    assert bad_bridge == 0
    assert bad_deferred == 0
    assert total_billed == total_recognized
