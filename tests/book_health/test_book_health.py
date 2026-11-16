"""On the book-health warehouse built once in conftest.py: the simulator's rules and planted patterns, the marts
against a pandas recomputation from the raw feeds, the late-claims split, the retention back-test, and the
committed results."""
from datetime import date

import duckdb
import pandas as pd
import pytest

from book_health import forecast as fc
from book_health.run import (
    BACKTEST,
    BRIEF,
    FORECAST,
    PROVINCE_MONTH,
    SUMMARY,
    backtest,
    backtest_csv,
    brief,
    forecast_csv,
    province_month_csv,
    summary,
    to_json,
)
from book_health.simulate import AS_OF, FIRST_MONTH, NORMAL_RATE_CHANGE, rate_change, renew_chance, simulate


@pytest.fixture(scope="module")
def con(db):
    with duckdb.connect(str(db), read_only=True) as c:
        yield c


@pytest.fixture(scope="module")
def bt(db):
    return backtest(db)


def test_rate_change_and_renew_chance():
    assert rate_change("ON", "auto", date(2025, 3, 31), 0.0) == NORMAL_RATE_CHANGE
    assert rate_change("ON", "auto", date(2025, 4, 1), 0.0) == 0.14
    assert rate_change("ON", "home", date(2025, 4, 1), 0.0) == NORMAL_RATE_CHANGE
    assert rate_change("AB", "home", date(2025, 1, 1), 0.0) == 0.10
    # broker auto in its second term at the usual increase: 0.88 - 0.01
    assert renew_chance("broker", "auto", 2, NORMAL_RATE_CHANGE) == pytest.approx(0.87)
    # from the third term on 3 points more; each point above the usual increase costs a point
    assert renew_chance("broker", "auto", 3, 0.14) == pytest.approx(0.87 + 0.03 - 0.10)


def test_simulation_is_seeded(book):
    again = simulate()
    pd.testing.assert_frame_equal(book.terms, again.terms)
    pd.testing.assert_frame_equal(book.claims, again.claims)


def test_feeds_hold_together(book):
    assert book.terms["term_id"].is_unique and book.claims["claim_id"].is_unique
    assert set(book.terms["policy_id"]) == set(book.policies["policy_id"])
    assert set(book.claims["term_id"]) <= set(book.terms["term_id"])
    assert (book.claims["reported_date"] <= AS_OF).all()
    assert (book.late_claims["reported_date"] > AS_OF).all() and (book.late_claims["loss_date"] <= AS_OF).all()
    assert (book.claims["loss_date"] >= book.claims["loss_date"].min()).all()
    # every claim's loss falls inside its term
    c = book.claims.merge(book.terms, on="term_id")
    assert ((c["loss_date"] >= c["start_date"]) & (c["loss_date"] < c["end_date"])).all()
    # the offered change is known exactly for terms that came due, and a renewal took the offered change
    due = book.terms["end_date"] <= AS_OF
    assert book.terms.loc[due, "renewal_offer_change"].notna().all()
    assert book.terms.loc[~due, "renewal_offer_change"].isna().all()
    nxt = book.terms.assign(term_number=book.terms["term_number"] - 1).merge(
        book.terms, on=["policy_id", "term_number"], suffixes=("_next", ""))
    assert (nxt["rate_change_next"] == nxt["renewal_offer_change"]).all()


def _truth(book) -> pd.DataFrame:
    """Retention and incurred per province and month, straight from the raw feeds."""
    t = book.terms.merge(book.policies, on="policy_id")
    ids = set(t["term_id"])
    t["renewed"] = [f"{p}-{n + 1}" in ids for p, n in zip(t["policy_id"], t["term_number"], strict=True)]
    t = t[(t["end_date"] <= AS_OF) & (t["end_date"] >= FIRST_MONTH.start_time.date())]
    t["month"] = pd.to_datetime(t["end_date"]).dt.to_period("M")
    ret = t.groupby(["province", "month"]).agg(renewals_due=("renewed", "size"), renewed=("renewed", "sum"))
    c = book.claims.merge(t[["term_id"]].drop_duplicates(), how="left", on="term_id")
    c = book.claims.merge(book.terms[["term_id", "policy_id"]], on=["term_id", "policy_id"]).merge(
        book.policies, on="policy_id")
    c["month"] = pd.to_datetime(c["loss_date"]).dt.to_period("M")
    inc = c.groupby(["province", "month"])["amount"].sum().rename("incurred")
    return ret.join(inc, how="outer").fillna(0)


def test_province_month_matches_a_pandas_recomputation(con, book):
    pm = con.sql("select * from province_month").df()
    pm["month"] = pd.to_datetime(pm["month_start"]).dt.to_period("M")
    got = pm.set_index(["province", "month"])
    want = _truth(book)
    joined = want.join(got[["renewals_due", "renewed", "incurred"]], rsuffix="_mart", how="outer").fillna(0)
    assert (joined["renewals_due"] == joined["renewals_due_mart"]).all()
    assert (joined["renewed"] == joined["renewed_mart"]).all()
    assert joined["incurred"].round(2).tolist() == joined["incurred_mart"].astype(float).round(2).tolist()


def test_earned_premium_adds_up_to_written(con, book):
    """Terms that start and end inside the covered months earn exactly what was written."""
    inside = book.terms[(book.terms["start_date"] >= FIRST_MONTH.start_time.date())
                        & (book.terms["end_date"] <= AS_OF)]
    earned = con.sql(f"""
        select sum(t.written_premium * (least(t.end_date, (m.m + interval 1 month)::date)
                                        - greatest(t.start_date, m.m::date)) / (t.end_date - t.start_date))
        from stg_book__terms as t
        join generate_series(date '{FIRST_MONTH.start_time.date()}', date '{AS_OF}', interval 1 month) as m (m)
          on t.start_date < (m.m + interval 1 month)::date and t.end_date > m.m::date
        where t.start_date >= date '{FIRST_MONTH.start_time.date()}' and t.end_date <= date '{AS_OF}'
    """).fetchone()[0]
    assert float(earned) == pytest.approx(inside["written_premium"].sum(), abs=0.5)
    # and the mart never earns more than the book wrote over its terms
    total = con.sql("select sum(earned_premium) from fct_segment_month").fetchone()[0]
    assert float(total) < book.terms["written_premium"].sum()


def test_planted_patterns_show_in_the_marts(con):
    hail = con.sql("""select sum(incurred) / sum(earned_premium) from fct_segment_month
                      where province = 'AB' and product = 'home' and month_start = '2024-07-01'""").fetchone()[0]
    assert hail > 3
    on = con.sql("""select sum(renewed) filter (where month_start < '2025-04-01') / sum(renewals_due)
                           filter (where month_start < '2025-04-01'),
                           sum(renewed) filter (where month_start >= '2025-04-01') / sum(renewals_due)
                           filter (where month_start >= '2025-04-01')
                    from fct_segment_month where province = 'ON' and product = 'auto'
                    and month_start >= '2024-04-01' and month_start < '2026-04-01'""").fetchone()
    assert on[0] - on[1] > 0.07
    ch = dict(con.sql("select channel, retention from (select channel, sum(renewed) / sum(renewals_due) as "
                      "retention from retention_by_segment group by 1)").fetchall())
    assert ch["digital"] < ch["direct"] < ch["broker"]
    growth = dict(con.sql("""select province, sum(new_policies) filter (where year(month_start) = 2025)
                                    / sum(new_policies) filter (where year(month_start) = 2022)
                             from province_month group by 1""").fetchall())
    assert max(growth, key=growth.get) == "AB" and min(growth, key=growth.get) == "QC"


def test_late_claims_understate_the_last_months(book):
    late = book.late_claims
    assert len(late) > 0
    assert pd.to_datetime(late["loss_date"]).min() > pd.Timestamp(AS_OF) - pd.Timedelta(days=150)


def test_forecast_rules_on_a_small_series():
    months = pd.period_range("2024-01", periods=4, freq="M")
    due = pd.Series([100.0, 100.0, 200.0, 100.0], index=months)
    renewed = pd.Series([90.0, 80.0, 140.0, 50.0], index=months)
    assert fc.forecast(due, renewed, months[2], "last_month") == pytest.approx(0.70)
    assert fc.forecast(due, renewed, months[2], "trailing_3") == pytest.approx(310 / 400)
    with pytest.raises(KeyError):  # 12 months of history are needed
        fc.forecast(due, renewed, months[2], "trailing_12")


def test_backtest_uses_only_months_up_to_the_origin(con, bt):
    pm = con.sql("select * from province_month").df()
    origin = pd.Period("2024-06", "M")
    changed = pm.copy()
    later = pd.to_datetime(changed["month_start"]).dt.to_period("M") > origin
    changed.loc[later, "renewed"] = 0  # nobody renews after the origin
    again = fc.backtest(changed)
    key = ["province", "origin", "horizon", "rule"]
    a = bt[bt["origin"] == origin].set_index(key)["forecast"]
    b = again[again["origin"] == origin].set_index(key)["forecast"]
    pd.testing.assert_series_equal(a.sort_index(), b.sort_index())
    assert (bt["target"] - bt["origin"]).map(lambda d: d.n).between(1, 3).all()


def test_score_is_weighted_by_renewals_due():
    bt = pd.DataFrame({"rule": ["r", "r"], "forecast": [0.90, 0.80], "actual": [0.80, 0.80], "due": [100, 300]})
    s = fc.score(bt, ["rule"]).iloc[0]
    assert s["mae_points"] == pytest.approx(2.5) and s["bias_points"] == pytest.approx(2.5)


def test_twelve_month_average_lags_a_rate_action(bt):
    on = bt[(bt["province"] == "ON") & (bt["target"] >= pd.Period("2025-04", "M"))
            & (bt["target"] < pd.Period("2025-10", "M"))]
    s = fc.score(on, ["rule"]).set_index("rule")
    assert s.loc["trailing_12", "bias_points"] > 3
    assert s.loc["trailing_3", "bias_points"] < s.loc["trailing_12", "bias_points"]


def test_committed_results_are_current(db, bt):
    s = summary(db, bt)
    assert SUMMARY.read_text() == to_json(s)
    assert PROVINCE_MONTH.read_text() == province_month_csv(db)
    assert BACKTEST.read_text() == backtest_csv(bt)
    assert FORECAST.read_text() == forecast_csv(db, bt)
    assert BRIEF.read_text() == brief(s)


def test_brief_numbers_come_from_the_summary(db, bt):
    s = summary(db, bt)
    text = brief(s)
    on = next(a for a in s["rate_actions"] if a["province"] == "ON")
    assert f"{100 * on['after']['retention']:.1f}%" in text
    assert f"{s['book']['in_force']:,}" in text
    assert f"{s['retention_forecast']['next_3_months']['renewals_due']:,}" in text
    assert "Simulated" in text
