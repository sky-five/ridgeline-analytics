from datetime import date

from revrec.billing import AS_OF, Billing, Subscription, from_engine, yesterday
from revrec.build import build
from revrec.parallel_run import compare


def test_sql_and_reference_agree_to_the_cent():
    billing = from_engine()
    compared, diffs = compare(build(billing), billing, AS_OF)
    assert compared > 150
    assert diffs == []


def test_sql_and_reference_agree_on_another_seed():
    billing = from_engine(seed=11, customers=150)
    _, diffs = compare(build(billing), billing, AS_OF)
    assert diffs == []


def test_parallel_run_catches_a_planted_error():
    billing = from_engine(customers=50)
    con = build(billing)
    con.execute("update fct_revenue_monthly set recognized_cents = recognized_cents + 1 "
                "where month_start = date '2026-03-01'")
    _, diffs = compare(con, billing, AS_OF)
    assert diffs == [d for d in diffs if d.startswith("revenue 2026-03-01")] and len(diffs) == 1


def test_reference_matches_a_hand_calculation():
    from revrec import reference

    b = Billing()
    s = Subscription("sub_1", "cus_1", "team", 1, "year")
    b.line(s, "subscription", date(2025, 1, 15), date(2025, 1, 15), date(2026, 1, 15), 120_000)
    assert reference.revenue_by_month(b)[date(2025, 1, 1)] == 5_589


def test_sql_and_reference_agree_as_of_yesterday():
    # The close follows the nightly date, not only the README snapshot.
    as_of = yesterday()
    billing = from_engine(as_of)
    compared, diffs = compare(build(billing, as_of=as_of), billing, as_of)
    assert compared > 201
    assert diffs == []
