"""The "Ask the funnel" tables hold governed values only, and real questions get answered from them.

Needs a built warehouse: run scripts/run_all.py first. Marked `warehouse`. Lives next to test_metrics.py: like
it, it opens MetricFlow's connection, which must come after the tests that open the warehouse read-only.
"""
from pathlib import Path

import duckdb
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "warehouse" / "ridgeline.duckdb"
pytestmark = [pytest.mark.warehouse, pytest.mark.skipif(not DB.exists(), reason="build the warehouse first")]


@pytest.fixture(scope="module")
def tables():
    from funnel_ask.answers import answers_table, vocab_table

    with duckdb.connect(str(DB)) as con:
        as_of = con.sql("select max(date_day) from fct_mrr_daily").fetchone()[0]
    answers = answers_table(as_of)
    return answers, vocab_table(answers)


def test_every_value_is_the_governed_metric(tables):
    from semantic import query

    answers, _ = tables
    got = answers[(answers.grain == "month") & (answers.metric == "cac") & (answers.channel != "all")]
    mf = query(["cac"], ["metric_time__month", "channel_day__marketing_channel"])
    mf = {(pd.Timestamp(m).date(), c): v for m, c, v in
          zip(mf["metric_time__month"], mf["channel_day__marketing_channel"], mf["cac"], strict=True)}
    assert len(got) > 100
    for r in got.itertuples():
        want = mf[(r.period, r.channel)]
        if pd.isna(want):  # e.g. CAC in a month with no paid conversions yet
            assert pd.isna(r.value)
        else:
            assert r.value == pytest.approx(float(want), rel=1e-12)


def test_each_funnel_metric_has_months_years_and_channels(tables):
    answers, vocab = tables
    per = answers.groupby("metric").agg(grains=("grain", "nunique"), channels=("channel", "nunique"))
    assert len(per) == 6 and (per.grains == 2).all() and (per.channels == 7).all()  # 6 channels + all
    assert set(vocab[vocab.kind == "channel"].target) == set(answers.channel) - {"all"}


def test_page_examples_are_answered(tables):
    from funnel_ask.ask import ask, connect

    con = connect(*tables)
    for q in ("What was CAC for Google Ads in March 2026?", "Free to paid by channel in 2025",
              "How many signups last month?", "Ad spend in 2025"):
        out = ask(con, q)
        assert (out.status == "answer").all() and out.value.notna().all(), q
    assert ask(con, "What is our churn rate?").status.tolist() == ["refused"]
