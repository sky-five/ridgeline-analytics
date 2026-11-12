"""Builds the ARR warehouse once (load + dbt build, about 8 seconds) and checks the bridge against revrec's
independent Python reference, the deal matching against the planted labels, and the committed results."""
import json
from datetime import date

import duckdb
import pytest

from arr_source_of_truth.crm_side import labels, won_deals_as_of
from arr_source_of_truth.load import AS_OF, dbt_build, load
from arr_source_of_truth.score import RESULTS, score
from revrec import reference
from revrec.billing import from_engine


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("arr") / "arr.duckdb"
    load(AS_OF, path)
    dbt_build(AS_OF, path)
    return path


@pytest.fixture(scope="module")
def con(db):
    with duckdb.connect(str(db), read_only=True) as c:
        yield c


@pytest.fixture(scope="module")
def summary(db):
    return score(AS_OF, db)


def test_labels_stay_out_of_the_warehouse(con):
    cols = {c for (c,) in con.execute(
        "select column_name from information_schema.columns where table_schema = 'raw_crm'").fetchall()}
    assert cols == {"deal_id", "customer_id", "deal_type", "close_date", "booked_arr_cents"}


def test_crm_export_is_deterministic_and_an_earlier_date_is_a_prefix():
    early, late = won_deals_as_of(date(2026, 3, 31)), won_deals_as_of(AS_OF)
    assert early.equals(won_deals_as_of(date(2026, 3, 31)))
    assert early.equals(late.iloc[: len(early)])


def test_bridge_matches_the_revrec_python_reference_every_month(con):
    ref = reference.arr_bridge(from_engine(AS_OF), AS_OF)
    rows = con.execute("select * from arr_bridge where month_start >= date '2025-01-01' order by 1").df()
    assert len(rows) == len(ref) == 21
    for r in rows.itertuples():
        want = ref[r.month_start.date()]
        got = {"opening": r.opening_arr_cents, "new": r.new_arr_cents, "reactivation": r.reactivation_arr_cents,
               "expansion": r.expansion_arr_cents, "contraction": r.contraction_arr_cents,
               "churn": r.churn_arr_cents, "closing": r.closing_arr_cents}
        assert got == want, r.month_start


def test_every_deal_lands_on_the_billing_change_it_came_from(summary):
    assert summary.wrong_matches == 0
    assert summary.deals_matched == summary.sales_led_billing_changes - summary.caught["missing_deal"]


def test_every_planted_mistake_is_caught_with_no_false_flags(summary):
    assert summary.false_flags == 0
    for defect, n in summary.planted.items():
        assert n > 0, defect
        # one annual deal closed in the last days of September and billing has not started it yet,
        # so it is awaiting billing, not yet comparable
        allowed = 1 if defect == "annual_at_billed" else 0
        assert summary.caught[defect] >= n - allowed, defect


def test_deals_awaiting_billing_closed_in_the_last_30_days(con):
    (oldest,) = con.execute("select min(close_date) from arr_deal_matches where status = 'awaiting_billing'").fetchone()
    assert oldest > date(2026, 8, 31)


def test_walk_closes_to_billing_and_the_bridge_every_month(con):
    bad = con.execute("""
        select count(*)
        from arr_booking_walk as w
        join arr_bridge as b using (month_start)
        where w.crm_booked_cents + w.duplicates_cents + w.won_not_billed_cents + w.awaiting_billing_cents
              + w.amount_fixes_cents + w.timing_cents + w.missing_deals_cents <> w.billing_sales_led_cents
           or w.net_change_cents <> b.closing_arr_cents - b.opening_arr_cents
           or w.billing_sales_led_cents <> b.new_arr_cents + b.reactivation_arr_cents + b.expansion_arr_cents
              + b.contraction_arr_cents + b.churn_arr_cents - w.seat_changes_cents - w.cancellations_cents
    """).fetchone()[0]
    assert bad == 0


def test_timing_nets_to_zero_over_all_billed_deals(con):
    # moving a deal from its close month to its billing month adds and subtracts the same amount,
    # except for deals closed in the last closed month whose billing starts after it
    (total,) = con.execute("select sum(timing_cents) from arr_booking_walk").fetchone()
    (spill,) = con.execute("""
        select coalesce(sum(billed_arr_cents), 0) from arr_deal_matches
        where change_key is not null and billed_month > (select max(month_start) from arr_months)
    """).fetchone()
    assert total == -spill


def test_labels_cover_every_planted_kind():
    kinds = set(labels()["defect"].dropna())
    assert kinds == {"missing_deal", "annual_at_billed", "amount_typo", "duplicate", "won_not_billed"}


def test_committed_results_match_the_code(summary):
    assert json.loads(RESULTS.read_text()) == json.loads(summary.to_json())
