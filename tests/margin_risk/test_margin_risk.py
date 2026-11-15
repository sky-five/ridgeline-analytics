"""Builds the margin warehouse once (simulate + load + dbt build, about 10 s) and checks the simulator's planted
patterns, the risk mart against an independent pandas recomputation from the raw feeds, the reconciliation
against the planted feed faults, and the committed results."""
from datetime import date

import duckdb
import numpy as np
import pandas as pd
import pytest

from margin_risk.load import dbt_build, load
from margin_risk.run import FINDINGS, FIRM_DAILY, SUMMARY, findings, firm_daily_csv, summary, to_json
from margin_risk.simulate import (
    CONCENTRATION_RATE,
    DUPLICATE_FILE_DATE,
    INTEREST_GAP_DATE,
    SHOCK_DAYS,
    SPLIT_DATE,
    SPLIT_SYMBOL,
    requirement,
    simulate,
)


@pytest.fixture(scope="module")
def book():
    return simulate()


@pytest.fixture(scope="module")
def db(tmp_path_factory, book):
    path = tmp_path_factory.mktemp("margin") / "margin.duckdb"
    load(path, book)
    dbt_build(path)
    return path


@pytest.fixture(scope="module")
def con(db):
    with duckdb.connect(str(db), read_only=True) as c:
        yield c


def test_requirement_raises_a_concentrated_holding_to_the_concentration_rate():
    rates = np.array([0.25, 0.30, 0.25])
    # 60% of the account in the first holding: it needs 40%, the others keep their own rate
    got = requirement(np.array([[600.0, 300.0, 100.0]]), rates)[0]
    assert got == pytest.approx(600 * CONCENTRATION_RATE + 300 * 0.30 + 100 * 0.25)
    # exactly half is not over half
    assert requirement(np.array([[500.0, 500.0, 0.0]]), rates)[0] == pytest.approx(500 * 0.25 + 500 * 0.30)
    assert requirement(np.zeros((1, 3)), rates)[0] == 0


def test_simulation_is_seeded(book):
    again = simulate()
    pd.testing.assert_frame_equal(book.ledger, again.ledger)
    pd.testing.assert_frame_equal(book.positions, again.positions)


def test_planted_patterns(book):
    px = book.prices.pivot(index="price_date", columns="symbol", values="close")
    before, after = px.loc[SHOCK_DAYS[0].date() - pd.Timedelta(days=3)], px.loc[SHOCK_DAYS[-1].date()]
    semis = book.securities.symbol[book.securities.sector == "semiconductors"]
    drop = after[semis] / before[semis] - 1
    assert drop.max() < -0.25 and drop.min() > -0.40
    others = book.securities.symbol[book.securities.sector != "semiconductors"]
    assert (after[others] / before[others] - 1).min() > -0.15
    s = px[SPLIT_SYMBOL]
    i = list(s.index).index(SPLIT_DATE)
    assert 0.40 < s.iloc[i] / s.iloc[i - 1] < 0.60  # the price halves on the ex-date
    dup = book.positions[book.positions.as_of_date == DUPLICATE_FILE_DATE]
    assert dup.loaded_at.nunique() == 2 and len(dup) == 2 * len(dup.drop_duplicates(["account_id", "symbol"]))
    assert set(book.labels.as_of_date) == {SPLIT_DATE, INTEREST_GAP_DATE}


def test_ledger_equity_moves_only_by_market_deposits_and_interest(book):
    """The books of record add up: no money appears or disappears outside P&L, deposits and interest."""
    led = book.ledger.assign(equity=lambda d: d.market_value + d.cash_balance)
    eq = led.pivot(index="as_of_date", columns="account_id", values="equity")
    px = book.prices.pivot(index="price_date", columns="symbol", values="close")
    pos = book.positions.drop_duplicates(["as_of_date", "account_id", "symbol"])
    lab = book.labels[book.labels.fault == "split_applied_late"].drop(columns="fault")
    fix = pos.merge(lab, on=["as_of_date", "account_id", "symbol"], how="left")
    fix["quantity"] = fix.true_value.fillna(fix.quantity)  # the true quantity, as the ledger has it
    q = fix.pivot_table(index=["as_of_date", "account_id"], columns="symbol", values="quantity", fill_value=0)
    days = list(eq.index)
    act = book.cash_activity.pivot_table(index="as_of_date", columns="account_id", values="amount", aggfunc="sum")
    for d0, d1 in zip(days[:-1], days[1:], strict=True):
        held = q.loc[d0].reindex(columns=px.columns, fill_value=0)
        ratio = pd.Series(1.0, index=px.columns)
        if d1 == SPLIT_DATE:
            ratio[SPLIT_SYMBOL] = 2
        pnl = (held * ratio * px.loc[d1] - held * px.loc[d0]).sum(axis=1)
        flows = act.loc[d1].reindex(eq.columns).fillna(0) if d1 in act.index else 0
        moved = eq.loc[d1] - eq.loc[d0] - pnl.reindex(eq.columns, fill_value=0) - flows
        assert moved.abs().max() < 0.05, d1


def test_risk_mart_matches_a_pandas_recomputation(con, book):
    pos = (book.positions.sort_values("loaded_at").drop_duplicates(["as_of_date", "account_id", "symbol"], keep="last")
           .merge(book.prices, left_on=["as_of_date", "symbol"], right_on=["price_date", "symbol"])
           .merge(book.securities, on="symbol"))
    pos["mv"] = (pos.quantity * pos.close).round(2)
    pos["share"] = pos.mv / pos.groupby(["as_of_date", "account_id"]).mv.transform("sum")
    rate = np.where(pos.share > 0.5, np.maximum(pos.maintenance_rate, CONCENTRATION_RATE), pos.maintenance_rate)
    # per holding, rounded half up to the cent, in whole cents so float rounding cannot differ from SQL's decimals
    cents, pct = (pos.mv * 100).round().astype("int64"), np.round(rate * 100).astype("int64")
    pos["req"] = ((cents * pct + 50) // 100) / 100
    acc = pos.groupby(["as_of_date", "account_id"])[["mv", "req"]].sum().reset_index()
    acc = book.cash.merge(acc, on=["as_of_date", "account_id"], how="left").fillna({"mv": 0, "req": 0})
    acc["in_call"] = acc.mv + acc.cash_balance < acc.req
    mart = con.sql("select as_of_date, account_id, market_value, requirement, in_call from fct_account_day").df()
    mart["as_of_date"] = mart.as_of_date.dt.date
    m = acc.merge(mart, on=["as_of_date", "account_id"], validate="one_to_one")
    assert len(m) == len(book.cash) == 240 * 128
    assert (m.mv - m.market_value).abs().max() < 0.01
    assert (m.req - m.requirement).abs().max() < 0.01
    assert (m.in_call_x == m.in_call_y).all()  # pandas, mart


def test_reconciliation_flags_exactly_the_planted_faults(con, book):
    flagged = set(con.sql("select as_of_date, account_id from reconciliation_account_day where is_break").fetchall())
    planted = set(map(tuple, book.labels[["as_of_date", "account_id"]].to_numpy()))
    assert flagged == planted
    days = con.sql("select as_of_date, market_value_breaks, cash_breaks from reconciliation_daily "
                   "where is_flagged order by 1").fetchall()
    assert [(d, m > 0, c > 0) for d, m, c in days] == [(SPLIT_DATE, True, False), (INTEREST_GAP_DATE, False, True)]


def test_repeated_positions_file_counts_once(con):
    d = DUPLICATE_FILE_DATE
    raw, kept = con.sql(f"""select (select count(*) from raw_margin.positions where as_of_date = '{d}'),
                                   (select count(*) from fct_position_day where as_of_date = '{d}')""").fetchone()
    assert raw == 2 * kept
    assert not con.sql(f"select is_flagged from reconciliation_daily where as_of_date = '{DUPLICATE_FILE_DATE}'"
                       ).fetchone()[0]


def test_margin_calls(con):
    calls = con.sql("select * from margin_calls").df()
    assert (calls.weekdays_in_call >= 1).all() and (calls.deficit_at_call > 0).all()
    # calls that start on a broken account-day all come from the late split
    broken = calls[calls.starts_on_break]
    assert len(broken) > 0 and set(broken.call_date.dt.date) == {SPLIT_DATE}
    real = calls[~calls.starts_on_break]
    assert real.was_concentrated.mean() > 0.9  # concentrated borrowers are the ones who get called
    deposits = con.sql("select account_id, as_of_date from raw_margin.cash_activity where kind = 'deposit'").df()
    dep = real[real.resolution == "deposit"].merge(deposits, left_on=["account_id", "cured_date"],
                                                    right_on=["account_id", "as_of_date"])
    assert len(dep) == (real.resolution == "deposit").sum()
    shock = real[(real.call_date >= SHOCK_DAYS[0]) & (real.call_date <= SHOCK_DAYS[-1] + pd.Timedelta(days=7))]
    assert len(shock) > 0


def test_pnl_is_unexplained_only_around_the_faults(con):
    days = [r[0] for r in con.sql("select distinct as_of_date from fct_account_pnl_day where abs(unexplained) > 0.05 "
                                  "order by 1").fetchall()]
    assert days == [SPLIT_DATE, date(2026, 4, 16), INTEREST_GAP_DATE, date(2026, 6, 1)]


def test_committed_results_are_current(db):
    s = summary(db)
    assert SUMMARY.read_text() == to_json(s)
    assert FIRM_DAILY.read_text() == firm_daily_csv(db)
    assert FINDINGS.read_text() == findings(s)
    assert s["checks"]["reconciliation"]["missed"] == 0 and s["checks"]["reconciliation"]["false_alarms"] == 0
