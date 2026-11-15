"""A seeded, simulated margin book for a small brokerage: 240 accounts trading 30 fictional securities on the
weekdays from 2026-01-02 to 2026-06-30.

Each day the simulator marks every holding at the close, applies corporate actions, posts margin interest on the
last weekday of the month, lets customers deposit after a margin call, liquidates accounts still short two days
after a call, and makes a few ordinary trades at the close. The true end-of-day state per account goes to the
ledger (the books of record). The operational feeds the marts are built from are the positions file, the cash
balance file, the price file, the corporate-action file and the cash activity file.

Planted for the marts and the reconciliation to find:

- semiconductors fall 27% to 36% over the week of 2026-03-16, so concentrated accounts go into margin call;
- SEM03 splits 2-for-1 on 2026-04-15, and the positions file applies the split one day late (still the old
  quantity on the ex-date), so the mart undervalues SEM03 holders that day;
- May's margin interest posts to the ledger on 2026-05-29 but is missing from that day's cash balance file;
- the positions file for 2026-02-11 is delivered twice; staging must keep one copy.

Where the feeds are wrong on purpose is kept in `labels`, out of the feeds, so the reconciliation can be scored.
"""
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

SEED = 518
FIRST_DAY, AS_OF = date(2026, 1, 2), date(2026, 6, 30)
ACCOUNTS = 240
SECTORS = {  # sector -> (daily volatility, maintenance rate)
    "software": (0.020, 0.30),
    "semiconductors": (0.024, 0.30),
    "banks": (0.014, 0.25),
    "energy": (0.018, 0.25),
    "utilities": (0.009, 0.25),
    "retail": (0.015, 0.25),
}
PER_SECTOR = 5
SHOCK_SECTOR, SHOCK_DAYS, SHOCK_DAILY = "semiconductors", pd.bdate_range("2026-03-16", "2026-03-20"), -0.07
SPLIT_SYMBOL, SPLIT_DATE, SPLIT_RATIO = "SEM03", date(2026, 4, 15), 2
INTEREST_GAP_DATE = date(2026, 5, 29)  # May interest missing from this day's cash file
DUPLICATE_FILE_DATE = date(2026, 2, 11)
INITIAL_RATE = 0.50  # a new purchase may borrow at most half its value
CONCENTRATION_SHARE, CONCENTRATION_RATE = 0.50, 0.40  # a holding over half the account's value needs 40%
INTEREST_RATE = 0.075  # yearly, on the debit balance, actual/360
DEPOSIT_CHANCE = 0.55  # a customer in call deposits the next day
LIQUIDATE_AFTER = 2  # weekdays after the call
TRADE_CHANCE = 0.04  # per account per day


@dataclass
class Book:
    accounts: pd.DataFrame
    securities: pd.DataFrame
    prices: pd.DataFrame
    corporate_actions: pd.DataFrame
    positions: pd.DataFrame  # the positions file as delivered (faults included)
    cash: pd.DataFrame  # the cash balance file as delivered (faults included)
    cash_activity: pd.DataFrame
    ledger: pd.DataFrame  # true end-of-day market value and cash per account
    labels: pd.DataFrame  # account-days where a feed is wrong on purpose, and why


def securities() -> pd.DataFrame:
    rows = []
    for s, (vol, rate) in SECTORS.items():
        for i in range(1, PER_SECTOR + 1):
            rows.append({"symbol": f"{s[:3].upper()}{i:02d}", "sector": s, "daily_vol": vol,
                         "maintenance_rate": rate})
    return pd.DataFrame(rows)


def requirement(mv: np.ndarray, rates: np.ndarray) -> np.ndarray:
    """Maintenance requirement per account (rows) from holdings' market values (accounts x symbols)."""
    total = mv.sum(axis=1, keepdims=True)
    share = np.divide(mv, total, out=np.zeros_like(mv), where=total > 0)
    applied = np.where(share > CONCENTRATION_SHARE, np.maximum(rates, CONCENTRATION_RATE), rates)
    return (mv * applied).sum(axis=1)


def _prices(rng, sec: pd.DataFrame, days: pd.DatetimeIndex) -> np.ndarray:
    n, k = len(days), len(sec)
    market = rng.normal(0.0004, 0.008, n)
    sectors = list(SECTORS)
    factor = {s: rng.normal(0, 0.6 * SECTORS[s][0], n) for s in sectors}
    shock = days.isin(SHOCK_DAYS)
    factor[SHOCK_SECTOR][shock] = SHOCK_DAILY + rng.normal(0, 0.004, shock.sum())
    out = np.empty((n, k))
    for j, r in sec.iterrows():
        idio = rng.normal(0, 0.8 * r.daily_vol, n)
        ret = market * rng.uniform(0.7, 1.3) + factor[r.sector] + idio
        ret[0] = 0
        out[:, j] = rng.uniform(20, 160) * np.exp(np.cumsum(ret))
    j = sec.index[sec.symbol == SPLIT_SYMBOL][0]
    out[:, j] *= 300 / out[days.get_loc(pd.Timestamp(SPLIT_DATE)) - 1, j]  # trades near $300 before its split
    out[days >= pd.Timestamp(SPLIT_DATE), j] /= SPLIT_RATIO
    return np.round(out, 2)


def simulate(seed: int = SEED) -> Book:
    rng = np.random.default_rng(seed)
    sec = securities()
    syms = sec.symbol.to_numpy()
    rates = sec.maintenance_rate.to_numpy()
    days = pd.bdate_range(FIRST_DAY, AS_OF)
    px = _prices(rng, sec, days)
    n_acc, k = ACCOUNTS, len(sec)
    acc_ids = np.array([f"MA{i:04d}" for i in range(1, n_acc + 1)])
    kinds = rng.choice(["individual", "joint", "corporate"], n_acc, p=[0.7, 0.2, 0.1])
    opened = pd.Timestamp("2019-01-01") + pd.to_timedelta(rng.integers(0, 2_500, n_acc), "D")

    # opening book: equity, leverage, holdings; one in six accounts is concentrated (often in semiconductors)
    equity = np.round(np.exp(rng.normal(11.3, 0.9, n_acc)), 2)
    leverage = np.where(rng.random(n_acc) < 0.3, 0.0, rng.uniform(0.1, 0.8, n_acc))  # loan / equity, at most 1
    q = np.zeros((n_acc, k))
    semis = np.flatnonzero(sec.sector == SHOCK_SECTOR)
    for a in range(n_acc):
        mv = equity[a] * (1 + leverage[a])
        held = rng.choice(k, rng.integers(3, 11), replace=False)
        w = rng.dirichlet(np.ones(len(held)))
        if rng.random() < 1 / 6:
            top = rng.choice(semis) if rng.random() < 0.7 else rng.choice(k)
            leverage[a] = rng.uniform(0.7, 0.98)
            mv = equity[a] * (1 + leverage[a])
            held = np.unique(np.append(held, top))
            w = np.full(len(held), 0.0)
            w[held == top] = rng.uniform(0.55, 0.85)
            rest = held != top
            w[rest] = (1 - w[~rest].sum()) * rng.dirichlet(np.ones(rest.sum()))
        q[a, held] = np.floor(mv * w / px[0, held])
    cash = np.round(equity - (q * px[0]).sum(axis=1), 2)
    margin = leverage > 0  # the rest are cash accounts: they never borrow

    split_j = int(np.flatnonzero(syms == SPLIT_SYMBOL)[0])
    accrued = np.zeros(n_acc)
    call_start = np.full(n_acc, -1)
    deficit_at_call = np.zeros(n_acc)
    pos_rows, cash_rows, act_rows, led_rows, lab_rows = [], [], [], [], []
    month_end = {d: (i + 1 == len(days) or days[i + 1].month != d.month) for i, d in enumerate(days)}

    for i, d in enumerate(days):
        p = px[i]
        if d.date() == SPLIT_DATE:
            q[:, split_j] *= SPLIT_RATIO
        if i > 0:  # deposits answering yesterday's calls
            for a in np.flatnonzero(call_start == i - 1):
                if rng.random() < DEPOSIT_CHANCE:
                    amt = round(float(deficit_at_call[a] * rng.uniform(1.1, 1.5)), 2)
                    cash[a] += amt
                    act_rows.append((d, acc_ids[a], "deposit", amt))
        mv = q * p
        eq = mv.sum(axis=1) + cash
        req = requirement(mv, rates)
        for a in np.flatnonzero((call_start >= 0) & (call_start == i - LIQUIDATE_AFTER) & (eq < req)):
            f = 1.0 if eq[a] <= 0 else min(1.0, 1 - 0.9 * eq[a] / req[a])
            sold = np.floor(q[a] * f) if f < 1 else q[a].copy()
            cash[a] += round(float((sold * p).sum()), 2)
            q[a] -= sold
        for a in np.flatnonzero(rng.random(n_acc) < TRADE_CHANCE):
            j = rng.integers(k)
            mv_a = q[a] * p
            e = mv_a.sum() + cash[a]
            if rng.random() < 0.5 and q[a, j] > 0:
                n = np.floor(q[a, j] * rng.uniform(0.2, 1.0))
            else:
                # a margin account buys only with excess equity, a cash account only with its cash
                room = e - requirement(mv_a[None], rates)[0] if margin[a] else cash[a]
                n = -np.floor(max(0.0, room) * rng.uniform(0.05, 0.25) / p[j])
            q[a, j] -= n
            cash[a] = round(cash[a] + n * p[j], 2)
        accrued += np.maximum(-cash, 0) * INTEREST_RATE / 360 * (1 if i == 0 else (d - days[i - 1]).days)
        posted = np.zeros(n_acc)
        if month_end[d]:
            posted = np.round(accrued, 2)
            cash -= posted
            accrued[:] = 0
            for a in np.flatnonzero(posted > 0):
                act_rows.append((d, acc_ids[a], "interest", -float(posted[a])))
        cash = np.round(cash, 2)

        mv = np.round(q * p, 2)
        eq = mv.sum(axis=1) + cash
        req = requirement(mv, rates)
        short = eq < req
        call_start[~short] = -1
        new = short & (call_start < 0)
        call_start[new] = i
        deficit_at_call[new] = (req - eq)[new]

        held = np.argwhere(q > 0)
        fq = q.copy()
        if d.date() == SPLIT_DATE:
            fq[:, split_j] = q[:, split_j] / SPLIT_RATIO
            for a in np.flatnonzero(q[:, split_j] > 0):
                lab_rows.append((d, acc_ids[a], "split_applied_late"))
        for a, j in held:
            pos_rows.append((d, acc_ids[a], syms[j], fq[a, j]))
        fcash = cash.copy()
        if d.date() == INTEREST_GAP_DATE:
            fcash = cash + posted
            for a in np.flatnonzero(posted > 0):
                lab_rows.append((d, acc_ids[a], "interest_missing_from_cash_file"))
        cash_rows += [(d, acc_ids[a], fcash[a]) for a in range(n_acc)]
        led_rows += [(d, acc_ids[a], mv[a].sum(), cash[a]) for a in range(n_acc)]

    positions = pd.DataFrame(pos_rows, columns=["as_of_date", "account_id", "symbol", "quantity"])
    positions["as_of_date"] = positions.as_of_date.dt.date
    positions["quantity"] = positions.quantity.astype("int64")
    positions["file_name"] = "positions_" + pd.to_datetime(positions.as_of_date).dt.strftime("%Y%m%d") + ".csv"
    positions["loaded_at"] = pd.to_datetime(positions.as_of_date) + pd.Timedelta(hours=19)
    dup = positions[positions.as_of_date == DUPLICATE_FILE_DATE].copy()
    dup["loaded_at"] += pd.Timedelta(hours=2)  # the same file again, two hours later
    positions = pd.concat([positions, dup], ignore_index=True)

    def frame(rows, cols):
        df = pd.DataFrame(rows, columns=cols)
        df["as_of_date"] = pd.to_datetime(df.as_of_date).dt.date
        return df

    px_df = pd.DataFrame(px, columns=syms)
    px_df["price_date"] = days.date
    prices = px_df.melt(id_vars="price_date", var_name="symbol", value_name="close")
    return Book(
        accounts=pd.DataFrame({"account_id": acc_ids, "account_type": kinds, "margin_enabled": margin,
                               "opened_on": opened.date}),
        securities=sec[["symbol", "sector", "maintenance_rate"]],
        prices=prices,
        corporate_actions=pd.DataFrame([{"symbol": SPLIT_SYMBOL, "ex_date": SPLIT_DATE, "action": "split",
                                         "ratio": float(SPLIT_RATIO)}]),
        positions=positions,
        cash=frame(cash_rows, ["as_of_date", "account_id", "cash_balance"]).round({"cash_balance": 2}),
        cash_activity=frame(act_rows, ["as_of_date", "account_id", "kind", "amount"]),
        ledger=frame(led_rows, ["as_of_date", "account_id", "market_value", "cash_balance"]).round(2),
        labels=frame(lab_rows, ["as_of_date", "account_id", "fault"]),
    )
