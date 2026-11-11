"""Opportunities: the two windows, the floors, the flags and the reason line."""
from datetime import date

import pandas as pd

from account_reviews.opportunities import flag, opportunities, window_totals


def metrics(rows):
    """rows: (account, 'YYYY-MM-01', orders, won, closed)"""
    return pd.DataFrame(rows, columns=["account", "month", "measurement_orders", "won_leads", "closed_leads"])


def health(rows):
    """rows: (account_id, mrr)"""
    return pd.DataFrame([{"account_id": a, "company_name": a.upper(), "region": "ON", "plan": "pro", "mrr": m,
                          "health_score": 50, "risk_band": "watch"} for a, m in rows])


def months(account, orders, won, closed, start="2026-05-01"):
    """Six monthly rows from start with the given per-month lists."""
    ms = pd.date_range(start, periods=len(orders), freq="MS").strftime("%Y-%m-%d")
    return [(account, m, o, w, c) for m, o, w, c in zip(ms, orders, won, closed, strict=True)]


def test_windows_split_three_and_three_and_ignore_other_months():
    m = metrics([("a", "2026-04-01", 50, 0, 0),  # before both windows
                 ("a", "2026-05-01", 2, 1, 2), ("a", "2026-07-01", 3, 1, 1),  # earlier window, June missing
                 ("a", "2026-08-01", 1, 0, 1), ("a", "2026-10-01", 1, 1, 1),  # last window
                 ("a", "2026-11-01", 99, 9, 9)])  # after the last complete month
    t = window_totals(m, date(2026, 10, 1)).iloc[0]
    assert (t["measurement_orders_before"], t["measurement_orders_after"]) == (5, 2)
    assert (t["won_leads_before"], t["closed_leads_before"]) == (2, 3)
    assert (t["won_leads_after"], t["closed_leads_after"]) == (1, 2)
    assert t["before_start"] == date(2026, 5, 1) and t["after_start"] == date(2026, 8, 1)


def test_account_active_only_in_one_window_gets_zeros_for_the_other():
    t = window_totals(metrics([("a", "2026-06-01", 9, 0, 0)]), date(2026, 10, 1)).iloc[0]
    assert t["measurement_orders_before"] == 9 and t["measurement_orders_after"] == 0


def _one(orders, won=(0,) * 6, closed=(0,) * 6):
    return flag(window_totals(metrics(months("a", list(orders), list(won), list(closed))), date(2026, 10, 1)))


def test_orders_falling_at_exactly_40_percent_and_not_below():
    assert _one([4, 3, 3, 2, 2, 2])["orders_falling"].tolist() == [True]  # 10 -> 6, -40%
    assert _one([4, 3, 3, 3, 2, 2]).empty  # 10 -> 7, -30%


def test_orders_floor_keeps_quiet_accounts_out():
    assert _one([2, 2, 1, 0, 0, 0]).empty  # 5 -> 0 is -100% but under the 6-order floor
    assert _one([2, 2, 2, 0, 0, 0])["orders_falling"].tolist() == [True]


def test_close_rate_dip_needs_15_points_and_enough_closed_leads():
    flat = [5] * 6
    got = _one(flat, won=[2, 2, 2, 1, 1, 1], closed=[3, 3, 3, 3, 3, 3])  # 6/9 = 67% -> 3/9 = 33%
    assert got["close_rate_dip"].tolist() == [True] and not got["orders_falling"].iloc[0]
    assert _one(flat, won=[2, 2, 2, 2, 2, 1], closed=[3] * 6).empty  # 67% -> 56%, 11 points: no flag
    # 10 of 20 -> 7 of 20 is exactly 15 points (float error would put it a hair under)
    assert _one(flat, won=[4, 3, 3, 3, 2, 2], closed=[7, 7, 6, 7, 7, 6])["close_rate_dip"].tolist() == [True]
    assert _one(flat, won=[2, 1, 1, 0, 0, 0], closed=[2, 2, 2, 2, 2, 2]).empty  # 6 closed each side: under floor


def test_reason_quotes_the_window_totals():
    r = _one([4, 4, 4, 1, 1, 1], won=[2, 2, 2, 1, 1, 1], closed=[3] * 6).iloc[0]
    assert r["n_flags"] == 2
    assert r["reason"] == ("Measurement orders fell from 12 to 3 (-75%). "
                           "Lead close rate fell from 67% (6 of 9) to 33% (3 of 9).")


def test_opportunities_only_paying_ordered_by_flags_then_mrr_and_link_reviews():
    m = metrics(months("big", [4, 4, 4, 1, 1, 1], [0] * 6, [0] * 6)
                + months("both", [4, 4, 4, 1, 1, 1], [2, 2, 2, 1, 1, 1], [3] * 6)
                + months("free", [9, 9, 9, 0, 0, 0], [0] * 6, [0] * 6)
                + months("steady", [3] * 6, [1] * 6, [2] * 6))
    h = health([("big", 900), ("both", 100), ("free", 0), ("steady", 500)])
    got = opportunities(h, m, date(2026, 11, 11), reviewed=["big"])
    assert got["account_id"].tolist() == ["both", "big"]
    assert got["rank"].tolist() == [1, 2]
    assert got["review_link"].isna().tolist() == [True, False] and got["review_link"].iloc[1] == "/account-reviews/big"
    assert (got["last_month"] == date(2026, 10, 1)).all()
