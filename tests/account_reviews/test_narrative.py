"""The written summary and its number check: the drafter only quotes the model, and the checker catches edits."""
from datetime import date

import pandas as pd
import pytest

from account_reviews.narrative import check, checked_draft, draft


def series():
    """12 months, Nov 2025 to Oct 2026. MRR 1,000 -> 1,250; recent 3 months vs the 3 before differ."""
    months = [date(2025, 11, 1), date(2025, 12, 1)] + [date(2026, m, 1) for m in range(1, 11)]
    net = [1000, 0, 0, 100, 0, 0, -50, 0, 0, 200, 0, 0]
    s = pd.DataFrame({"month": months, "net_new_mrr": [float(x) for x in net]})
    s["mrr"] = s["net_new_mrr"].cumsum()
    s["tickets"] = [1, 0, 0, 2, 0, 0, 1, 1, 0, 0, 2, 1]
    s["measurement_orders"] = [4] * 12
    s["redo_orders"] = [0, 1, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0]
    s["leads"] = [10] * 12
    s["closed_leads"] = [5] * 12
    s["won_leads"] = [2, 2, 2, 2, 2, 2, 1, 1, 1, 4, 3, 3]
    return s


HEADER = pd.Series({"account_id": "a1", "company_name": "Ridge 9 Roofing Co.", "mrr": 1250.0,
                    "health_score": 64, "risk_band": "at_risk"})


def test_draft_says_what_the_series_says():
    text = draft(HEADER, series())
    assert text == (
        "Ridge 9 Roofing Co. ended October 2026 at $1,250 MRR, up $250 (25%) from $1,000 at the end of "
        "November 2025. The largest monthly MRR change was a gain of $1,000 in November 2025. "
        "In the last 3 months it closed 15 homeowner leads and won 10 (67%), against 20% in the 3 months before. "
        "It ordered 48 measurement reports in 12 months and asked for a redo on 3 (6%). "
        "It opened 3 support tickets in the last 3 months and 2 in the 3 months before. "
        "Health score: 64 (at risk).")


def test_every_number_in_the_draft_is_checked_and_matches():
    text, n = checked_draft(HEADER, series())
    result = check(text, HEADER, series())
    assert result.ok and n == len(result.numbers)
    kinds = [f.kind for f in result.numbers]
    # the company name's 9 is not read as a number; months and window lengths are checked too
    assert kinds.count("month") == 3 and kinds.count("window") == 5 and n == 23
    assert "9" not in [f.text for f in result.numbers]


@pytest.mark.parametrize("old, new", [
    ("$1,250 MRR", "$1,260 MRR"),  # wrong dollar amount
    ("(25%)", "(30%)"),  # wrong percentage
    ("won 10 (67%)", "won 11 (67%)"),  # wrong count
    ("October 2026", "October 2027"),  # month outside the window
    ("last 3 months it closed", "last 4 months it closed"),  # a window the model has no figures for
])
def test_an_edited_number_fails_the_check(old, new):
    text = draft(HEADER, series())
    assert check(text, HEADER, series()).ok
    bad = text.replace(old, new)
    assert bad != text
    result = check(bad, HEADER, series())
    assert not result.ok and len(result.problems) >= 1


def test_months_are_only_held_to_the_window():
    # a known limit: a month is checked against the window, not paired with the value next to it, so the
    # wrong month passes while a wrong amount next to it fails
    text = "The largest monthly MRR change was a gain of $1,000 in March 2026."
    assert check(text, HEADER, series()).ok
    assert not check("The largest monthly MRR change was a gain of $1,075 in March 2026.", HEADER, series()).ok


def test_a_number_must_match_its_own_topic():
    # 48 is the measurement total; quoted as tickets it matches nothing on the tickets topic
    assert check("It ordered 48 measurement reports.", HEADER, series()).ok
    result = check("It opened 48 support tickets.", HEADER, series())
    assert not result.ok and result.problems[0].startswith("'48' (count)")


def test_precision_follows_the_text():
    # 10 won of 15 closed is 66.67%: "67%" and "66.7%" pass, "66%" and "66.6%" do not
    for ok in ("67%", "66.7%"):
        assert check(f"Won {ok} of homeowner leads.", HEADER, series()).ok
    for bad in ("66%", "66.6%"):
        assert not check(f"Won {bad} of homeowner leads.", HEADER, series()).ok


def test_checked_draft_refuses_a_summary_that_does_not_match(monkeypatch):
    import account_reviews.narrative as nar

    monkeypatch.setattr(nar, "draft", lambda h, s: "It opened 99 support tickets in the last 3 months.")
    with pytest.raises(ValueError, match="'99'"):
        nar.checked_draft(HEADER, series())


def test_flat_mrr_and_no_leads():
    s = series()
    s["net_new_mrr"] = [500.0] + [0.0] * 11
    s["mrr"] = 500.0
    s[["closed_leads", "won_leads"]] = 0
    s["tickets"] = [0] * 9 + [1, 0, 0]
    h = HEADER.copy()
    h["mrr"] = 500.0
    text, _ = checked_draft(h, s)
    assert "at $500 MRR, the same as at the end of November 2025." in text
    assert "homeowner leads" not in text and "largest monthly" not in text
    assert "It opened 1 support ticket in the last 3 months" in text
