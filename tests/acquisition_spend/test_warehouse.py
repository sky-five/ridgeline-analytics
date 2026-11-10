"""On a built warehouse: the CAC ties to the governed spend and funnel, and the yield reproduces the CAC.

On the 2026-06-30 snapshot the committed results must also match (`python -m acquisition_spend --check` in CI)."""
from pathlib import Path

import duckdb
import pytest

from acquisition_spend import report, whatif
from acquisition_spend.cac import channel_cac, in_window
from acquisition_spend.load import load, warehouse_path

pytestmark = [pytest.mark.warehouse,
              pytest.mark.skipif(not Path(warehouse_path()).exists(), reason="build the warehouse first")]


@pytest.fixture(scope="module")
def data():
    return load()


def test_cac_ties_to_the_marts(data):
    signups, spend, as_of = data
    w = report.windows(as_of)["cac"]
    cac = channel_cac(signups, spend, w).set_index("channel")
    with duckdb.connect(str(warehouse_path()), read_only=True) as con:
        usd, paid, n = con.execute(
            "select (select sum(spend_usd) from fct_marketing_channel_daily where date_day between ? and ?),"
            " count_if(is_paid_60d), count(*) from fct_account_funnel where cast(signup_at as date) between ? and ?",
            [w.start.date(), w.end.date()] * 2).fetchone()
    assert cac.spend_usd["all channels"] == pytest.approx(float(usd))
    assert cac.paid_60d["all channels"] == paid and cac.signups["all channels"] == n
    assert 0 < cac.cac_usd["all channels"] < cac.cac_usd["paid channels"]


def test_expected_paid_from_the_yield_is_close_to_actual_on_the_same_window(data):
    signups, spend, as_of = data
    w = report.windows(as_of)["cac"]
    y = whatif.fit(signups, spend, w)
    budget = in_window(spend, "date_day", w).groupby("channel").spend_usd.sum()
    budget = budget[budget > 0]
    actual = channel_cac(signups, spend, w).set_index("channel").paid_60d["paid channels"]
    assert whatif.predict_paid(y, budget).sum() == pytest.approx(actual, rel=0.05)


def test_higher_score_deciles_convert_more(data):
    signups, spend, as_of = data
    rate = whatif.fit(signups, spend, report.windows(as_of)["cac"]).decile_rate
    assert rate[10] > rate[9] > rate[8] > rate[1:7].max()
