"""Account review tables: which accounts, and the 12-month series each review page reads."""
from datetime import date

import pandas as pd
import pytest

from account_reviews.reviews import (
    MONTHLY_METRICS,
    last_complete_month,
    monthly_series,
    pick_accounts,
    review_tables,
    talking_points,
)


def health(rows):
    cols = ["account_id", "company_name", "mrr", "health_score", "risk_band"]
    return pd.DataFrame(rows, columns=cols)


def metrics(rows):
    """rows: (account, 'YYYY-MM-01', net_new_mrr, tickets, orders, redos, leads, won, closed)"""
    return pd.DataFrame(rows, columns=["account", "month", *MONTHLY_METRICS])


def test_picks_largest_mrr_with_stable_ties():
    h = health([("a3", "C", 200, 90, "healthy"), ("a1", "A", 300, 50, "watch"),
                ("a2", "B", 200, 80, "healthy"), ("a4", "D", 100, 20, "at_risk")])
    assert pick_accounts(h, 3)["account_id"].tolist() == ["a1", "a2", "a3"]


def test_last_complete_month():
    assert last_complete_month(date(2026, 11, 8)) == date(2026, 10, 1)
    assert last_complete_month(date(2026, 1, 31)) == date(2025, 12, 1)


def test_series_fills_gaps_and_mrr_is_running_sum_from_first_month():
    m = metrics([("a1", "2024-03-01", 100, 0, 0, 0, 0, 0, 0),  # long before the window: still counts
                 ("a1", "2025-12-01", 50, 2, 3, 1, 4, 1, 2),
                 ("a1", "2026-10-01", -30, 1, 0, 0, 0, 0, 0),
                 ("a1", "2026-11-01", 999, 9, 9, 9, 9, 9, 9),  # after the last complete month: dropped
                 ("zz", "2026-01-01", 500, 1, 1, 1, 1, 1, 1)])  # not reviewed: dropped
    s = monthly_series(m, ["a1"], date(2026, 10, 1))
    assert len(s) == 12
    assert s["month"].tolist()[0] == date(2025, 11, 1) and s["month"].tolist()[-1] == date(2026, 10, 1)
    by = s.set_index("month")
    assert by.loc[date(2025, 11, 1), "mrr"] == 100
    assert by.loc[date(2025, 12, 1), "mrr"] == 150
    assert by.loc[date(2026, 10, 1), "mrr"] == 120
    assert by.loc[date(2026, 3, 1), "tickets"] == 0  # a gap month counts as zero
    assert s["tickets"].sum() == 3 and s["measurement_orders"].sum() == 3


def test_series_for_a_new_account_starts_at_zero():
    s = monthly_series(metrics([("a1", "2026-09-01", 80, 0, 0, 0, 0, 0, 0)]), ["a1"], date(2026, 10, 1))
    assert len(s) == 12 and s["mrr"].tolist() == [0] * 10 + [80, 80]


def test_talking_points_only_use_numbers_from_the_page():
    s = pd.DataFrame({"month": [date(2026, m, 1) for m in (8, 9, 10)], "mrr": [100.0, 150.0, 150.0],
                      "tickets": [1, 0, 2], "measurement_orders": [2, 2, 0], "redo_orders": [1, 0, 0],
                      "won_leads": [1, 1, 0], "closed_leads": [2, 2, 0]})
    pts = talking_points(pd.Series({"health_score": 70, "risk_band": "at_risk"}), s)
    assert pts == ["MRR grew from $100 to $150 over the last 3 months.",
                   "Closed 4 homeowner leads and won 2 (50%).",
                   "Ordered 4 measurement reports; asked for 1 redo(s).",
                   "Opened 3 support ticket(s).",
                   "Health score 70 (at risk)."]


def test_review_tables_line_up():
    h = health([(f"a{i}", f"Co {i}", 100 * i, 80, "healthy") for i in range(1, 6)])
    m = metrics([(f"a{i}", "2025-01-01", 100 * i, i, 0, 0, 0, 0, 0) for i in range(1, 6)])
    t = review_tables(h, m, date(2026, 11, 8), n=3)
    head, series = t["account_review"], t["account_review_monthly"]
    assert head["account_id"].tolist() == ["a5", "a4", "a3"] and head["rank"].tolist() == [1, 2, 3]
    assert set(series["account_id"]) == {"a5", "a4", "a3"} and len(series) == 3 * 12
    # MRR at the end of the window matches the header's MRR when the history is complete
    last = series[series["month"] == date(2026, 10, 1)].set_index("account_id")["mrr"]
    assert last.to_dict() == pytest.approx(head.set_index("account_id")["mrr"].to_dict())
    assert all(tp.startswith("MRR held at") for tp in head["talking_points"])
