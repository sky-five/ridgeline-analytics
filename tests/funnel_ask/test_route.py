"""The router on a small hand-made answers table. No warehouse needed."""
from datetime import date

import pandas as pd
import pytest

from funnel_ask.ask import ask, connect, literal
from funnel_ask.vocab import METRICS, normalize, vocab_rows

CHANNELS = ["google_ads", "trade_show", "organic"]


def _row(metric, grain, start, channel, value, complete=True):
    return {"metric": metric, "label": metric.upper(), "description": "", "grain": grain, "period": start,
            "month_num": f"{start.month:02d}", "year": str(start.year),
            "period_label": start.strftime("%b %Y") if grain == "month" else str(start.year),
            "channel": channel, "value": value, "value_shown": f"{value:g}", "complete": complete,
            "mf_query": f"mf query --metrics {metric}"}


@pytest.fixture(scope="module")
def con():
    rows = []
    for m in METRICS:
        for i, start in enumerate([date(2025, 3, 1), date(2026, 2, 1), date(2026, 3, 1), date(2026, 4, 1)]):
            done = start < date(2026, 4, 1)  # April is the open month
            rows.append(_row(m.name, "month", start, "all", 100 + i, done))
            rows += [_row(m.name, "month", start, ch, 10 * (j + 1) + i, done) for j, ch in enumerate(CHANNELS)]
        rows.append(_row(m.name, "year", date(2025, 1, 1), "all", 1000))
        rows.append(_row(m.name, "year", date(2026, 1, 1), "all", 500, False))
    return connect(pd.DataFrame(rows), pd.DataFrame(vocab_rows(CHANNELS)))


@pytest.mark.parametrize("question, metric, channel, period", [
    ("What was CAC for Google Ads in March 2026?", "cac", "google_ads", "Mar 2026"),
    ("how many signups did we get?", "signups", "all", "Mar 2026"),  # latest complete month, not open April
    ("Ad spend on trade shows, Feb 2026", "ad_spend", "trade_show", "Feb 2026"),
    ("spend per paid conversion", "cac", "all", "Mar 2026"),  # longest phrase wins over "spend"
    ("trial-to-paid rate in 2025", "free_to_paid_60d", "all", "2025"),  # a year alone asks for the year
    ("activation in march", "activation_rate", "all", "Mar 2026"),  # a month alone: the latest March
    ("SIGNUPS... APRIL!!", "signups", "all", "Apr 2026"),
])
def test_questions_route_to_one_governed_value(con, question, metric, channel, period):
    out = ask(con, question)
    assert len(out) == 1
    r = out.iloc[0]
    assert (r.status, r.metric, r.channel, r.period_label) == ("answer", metric, channel, period)


def test_an_open_period_says_it_is_not_final(con):
    assert "not final yet" in ask(con, "signups in april 2026").iloc[0].reply
    assert "not final" not in ask(con, "signups in march 2026").iloc[0].reply


def test_by_channel_lists_every_channel_and_no_total(con):
    out = ask(con, "CAC by channel in February 2026")
    assert sorted(out["channel"]) == sorted(CHANNELS)
    assert list(out["value"]) == sorted(out["value"], reverse=True)


@pytest.mark.parametrize("question", [
    "What's our churn rate?", "How much MRR did we add?", "", "'; drop table funnel_answers; --",
])
def test_questions_without_a_funnel_metric_are_refused(con, question):
    out = ask(con, question)
    assert list(out["status"]) == ["refused"]
    assert out.iloc[0].value is None or pd.isna(out.iloc[0].value)


def test_a_period_with_no_value_is_not_guessed(con):
    out = ask(con, "signups in July 2024")
    assert list(out["status"]) == ["no_data"]


def test_quotes_in_a_question_are_data_not_sql(con):
    assert literal("it's") == "'it''s'"
    assert ask(con, "what's CAC for google's ads?").iloc[0].metric == "cac"


def test_phrases_are_stored_normalized_and_unique():
    rows = vocab_rows(CHANNELS)
    assert all(r["phrase"] == normalize(r["phrase"]) for r in rows)
    assert len({(r["kind"], r["phrase"]) for r in rows}) == len(rows)
    assert {r["target"] for r in rows if r["kind"] == "metric"} == {m.name for m in METRICS}
