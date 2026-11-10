"""Hand-checked CAC and what-if numbers on a tiny made-up history (no warehouse needed)."""
import pandas as pd
import pytest

from acquisition_spend import whatif
from acquisition_spend.cac import Window, channel_cac

JAN = Window(pd.Timestamp("2025-01-01"), pd.Timestamp("2025-01-31"))
FEB = Window(pd.Timestamp("2025-02-01"), pd.Timestamp("2025-02-28"))


def _signups(month: str, rows: list[tuple[str, int, int, int]]) -> pd.DataFrame:
    """rows: (channel, decile, signups, of which paid)."""
    out, i = [], 0
    for ch, dec, n, paid in rows:
        for k in range(n):
            i += 1
            out.append({"account_id": f"{month}-{i}", "signup_date": pd.Timestamp(f"{month}-10"), "channel": ch,
                        "is_paid_60d": k < paid, "is_mature": True, "decile": dec})
    return pd.DataFrame(out)


def _all_deciles(month: str) -> list[tuple[str, int, int, int]]:
    # organic fills every decile so the pooled rates exist: decile d has 10 signups, d-1 of them paid
    return [("organic", d, 10, d - 1) for d in range(1, 11)]


@pytest.fixture
def history():
    jan = _signups("2025-01", _all_deciles("2025-01") + [
        ("ads", 1, 80, 0), ("ads", 10, 20, 9),  # 100 signups, 9 paid
        ("show", 10, 10, 9),                     # 10 signups, 9 paid
    ])
    feb = _signups("2025-02", _all_deciles("2025-02") + [("ads", 1, 80, 2), ("ads", 10, 20, 10), ("show", 10, 5, 3)])
    spend = pd.DataFrame({
        "date_day": pd.to_datetime(["2025-01-05", "2025-01-06", "2025-01-07", "2025-02-05", "2025-02-06"]),
        "channel": ["ads", "ads", "show", "ads", "show"],
        "spend_usd": [600.0, 400.0, 5000.0, 1000.0, 2500.0],
    })
    return pd.concat([jan, feb], ignore_index=True), spend


def test_channel_cac_is_spend_over_paid_in_the_same_window(history):
    signups, spend = history
    cac = channel_cac(signups, spend, JAN).set_index("channel")
    assert cac.cac_usd["ads"] == pytest.approx(1000 / 9)
    assert cac.cac_usd["show"] == pytest.approx(5000 / 9)
    assert cac.cac_usd["organic"] == 0  # no spend, still counted
    assert cac.cac_usd["paid channels"] == pytest.approx(6000 / 18)
    assert cac.cac_usd["all channels"] == pytest.approx(6000 / (18 + 45))
    assert cac.signups["all channels"] == 210
    assert list(cac.index[:3]) == ["ads", "show", "organic"]  # paid channels by CAC, then free ones


def test_immature_signups_are_refused(history):
    signups, spend = history
    signups.loc[0, "is_mature"] = False
    with pytest.raises(ValueError, match="not known yet"):
        channel_cac(signups, spend, JAN)


def test_yield_is_signups_per_dollar_times_decile_mix_times_decile_rate(history):
    signups, spend = history
    y = whatif.fit(signups, spend, JAN)
    # pooled rates: decile 1 = (0 organic + 0 ads) / 90, decile 10 = (9 + 9 + 9) / 40
    assert y.decile_rate[1] == pytest.approx(0)
    assert y.decile_rate[10] == pytest.approx(27 / 40)
    assert y.paid_per_signup["ads"] == pytest.approx(0.2 * 27 / 40)
    assert y.paid_per_1k["ads"] == pytest.approx(1000 * (100 / 1000) * 0.2 * 27 / 40)  # 13.5
    assert y.paid_per_1k["show"] == pytest.approx(1000 * (10 / 5000) * 27 / 40)  # 1.35
    assert "organic" not in y.paid_per_1k.index  # no spend, no per-dollar yield
    assert y.top_decile_cost(1)["ads"] == pytest.approx(1000 / 20)


def test_moving_budget_to_the_better_yield_adds_paid_accounts(history):
    signups, spend = history
    y = whatif.fit(signups, spend, JAN)
    budget = pd.Series({"ads": 1000.0, "show": 5000.0})
    r = whatif.move(y, budget, "show", "ads", 1000)
    assert r["paid_before"] == pytest.approx(13.5 + 6.75)
    assert r["paid_change"] == pytest.approx(13.5 - 1.35)
    assert r["cac_after"] == pytest.approx(6000 / r["paid_after"])
    with pytest.raises(ValueError, match="cannot move"):
        whatif.move(y, budget, "ads", "show", 2000)
    with pytest.raises(ValueError, match="no spend history"):
        whatif.predict_paid(y, pd.Series({"radio": 10.0}))


def test_all_moves_are_best_first_and_symmetric_in_count(history):
    signups, spend = history
    y = whatif.fit(signups, spend, JAN)
    moves = whatif.all_moves(y, pd.Series({"ads": 1000.0, "show": 5000.0}))
    assert list(zip(moves.src, moves.dst, strict=True)) == [("show", "ads"), ("ads", "show")]
    assert moves.moved_usd.tolist() == [500.0, 100.0]


def test_backtest_predicts_the_later_window_from_its_spend(history):
    signups, spend = history
    bt = whatif.backtest(signups, spend, JAN, FEB).set_index("channel")
    assert bt.predicted_paid["ads"] == pytest.approx(1000 * 13.5 / 1000)
    assert bt.predicted_paid["show"] == pytest.approx(2500 * 1.35 / 1000)
    assert bt.actual_paid["ads"] == 12 and bt.actual_paid["show"] == 3
    assert bt.actual_paid["paid channels"] == 15
    assert bt.error["paid channels"] == pytest.approx(13.5 + 3.375 - 15)
    with pytest.raises(ValueError, match="after the fit window"):
        whatif.backtest(signups, spend, FEB, JAN)


def test_last_mature_months_stops_before_the_60_day_cutoff():
    w = Window.last_mature_months(pd.Timestamp("2026-06-30"), 12)
    assert (w.start, w.end) == (pd.Timestamp("2025-05-01"), pd.Timestamp("2026-04-30"))
    # on 2026-07-01 the last mature day is 2026-05-02, so May is still not whole
    w = Window.last_mature_months(pd.Timestamp("2026-07-01"), 1)
    assert (w.start, w.end) == (pd.Timestamp("2026-04-01"), pd.Timestamp("2026-04-30"))
    w = Window.last_mature_months(pd.Timestamp("2026-07-30"), 1)
    assert (w.start, w.end) == (pd.Timestamp("2026-05-01"), pd.Timestamp("2026-05-31"))
