# Margin risk mart

Risk and finance marts for a brokerage's margin book, on a simulated book of accounts, positions, prices and
cash, with a reconciliation that flags the days the marts drift from the ledger. Everything runs on DuckDB; the
marts are a small dbt project. Simulated data only; the securities are fictional.

```
python -m margin_risk          # simulate, load, dbt build, write results/
python -m margin_risk --check  # rebuild and fail if results/ is out of date (CI runs this)
```

## The data

`simulate.py` (seeded) runs 240 accounts (181 allowed to borrow, the rest cash accounts) holding 30 fictional
securities in six sectors over the 128 weekdays from 2026-01-02 to 2026-06-30. Each day it marks holdings at the
close, lets customers deposit after a margin call, liquidates an account still short two weekdays after its call,
posts margin interest (7.5% a year on the debit balance) on the last weekday of the month, and makes a few trades
at the close. Borrowers buy only with excess equity, cash accounts only with their cash.

The marts are built from the feeds a back office gets each evening: accounts, securities, prices (not adjusted for
splits), corporate actions, the positions file, the cash balance file and the cash activity file (deposits and
interest). The true end-of-day market value and cash per account go to the ledger, the books of record.

Planted:

| planted | what it does |
|---|---|
| semiconductor sell-off, week of 2026-03-16 | the five semiconductor stocks fall 26.7% to 35.7%; one in six accounts is concentrated, most in semiconductors |
| SEM03 2-for-1 split on 2026-04-15 | the positions file still carries the pre-split quantity on the ex-date |
| May margin interest, 2026-05-29 | posted in the ledger, missing from that day's cash balance file |
| positions file for 2026-02-11 | loaded twice, two hours apart |

Where a feed is wrong, and the true quantity or cash, goes to `labels.feed_faults`. The dbt models never read
it; `check.py` scores the reconciliation against it.

## The models

| model | grain | what it is for |
|---|---|---|
| `stg_margin__positions` | account x security x day | the positions file with repeat loads removed (latest load kept) |
| `fct_position_day` | account x security x day | market value at the close and the maintenance requirement: the security's rate (25% or 30%), raised to 40% for a holding over half the account |
| `fct_account_day` | account x day | **risk mart**: market value, loan (debit balance), equity, requirement, excess, collateral coverage, margin utilisation, top holding, in call |
| `fct_account_pnl_day` | account x day | **finance mart**: market P&L on yesterday's holdings (split-adjusted), deposits, interest, and the change in equity they leave unexplained |
| `margin_calls` | call | a run of weekdays below requirement: deficit, length, how it ended (deposit, liquidation, market, open), and whether it starts on an account-day that does not reconcile |
| `concentration_by_symbol` | security x day | share of borrowers' securities, borrowers holding it, borrowers concentrated in it |
| `daily_firm_summary` | day | the whole book: totals, coverage, utilisation, calls, P&L, interest income |
| `reconciliation_account_day` | account x day | mart market value and cash against the ledger; a difference of $1 or more is a break |
| `reconciliation_daily` | day | mart totals against ledger totals, drift, accounts broken; a day with any break is flagged |

Definitions: loan is the debit cash balance. Collateral coverage is market value less each holding's requirement,
over the loan; below 1 is a margin call, the same as equity below requirement (a dbt test holds the two to each
other). Margin utilisation is the loan over what the holdings could borrow at the 50% initial rate. Money is
decimal throughout, so totals do not depend on the order threads add them up.

dbt tests: not-null and accepted values, unique days, and five singular tests (one row per account and day; a
repeated file counts once; a call means coverage below 1; accounts add up to the firm; on account-days that
reconcile today and yesterday, market P&L, deposits and interest explain all of the change in equity).

## What it shows

On 2026-06-30, 179 borrowers owe $14,116,049 against $38,078,684 of securities in the book. Collateral coverage is
1.58 and borrowers use 90.6% of what they could borrow. 42 borrowers hold over half their account in one security.

There are 62 real margin calls over the half year, from 18 accounts and none before the sell-off. All are in
concentrated accounts with a semiconductor as the largest holding; 10 start in the sell-off week or the week
after, the other 52 later, many of them the same account called again. They were $91,567 short on the day of the call and spent a median 2 weekdays in call;
18 ended with a deposit, 24 with a liquidation, 19 when prices recovered, 1 is still open. 7 more calls start on
2026-04-15 and are not real: the positions file undervalued SEM03 holders that day.

## The reconciliation

The reconciliation compares 30,720 account-days with the ledger and flags 252 on two days, exactly the planted
ones (0 missed, 0 false alarms):

| day | market value drift | cash drift | accounts | cause |
|---|---:|---:|---:|---|
| 2026-04-15 | -$418,103 | $0 | 77 | positions file still has SEM03's pre-split quantity on its ex-date |
| 2026-05-29 | $0 | $80,589 | 175 | May's margin interest is in the ledger but not in the cash file |

The repeated positions file for 2026-02-11 (3,594 rows for 1,797 holdings) does not break: staging keeps one
load. Counted twice it would be $35,103,999 over the ledger.

The P&L mart sees both faults too, but on two days each: equity is unexplained on the fault day and again,
reversed, the next weekday. It can say something moved; only the ledger says which day is wrong. A generated
[findings note](results/findings.md) has the same numbers; `results/firm_daily.csv` is the firm summary by day
with the reconciliation flag.

## The dashboard page

The site's [Margin risk page](https://sky-five.github.io/ridgeline-analytics/margin-risk/) shows the book on
2026-06-30 ($14,116,049 lent against $38,078,684 of securities, coverage 1.58, utilisation 90.6%), coverage and
utilisation by weekday with the sell-off marked, margin calls started per day with the 7 split-day calls shown
apart, how the 62 real calls ended, each sector's share of borrowers' securities over time and each security's on
four days (start, the Friday before the sell-off, its last day, the as-of day), daily and unexplained P&L, and the
two flagged days with their cause. `run.py` also writes `results/margin_calls.csv`, `results/sector_daily.csv`
and `results/concentration.csv` (all in `--check`); `report.py` turns the committed results into eight
`reporting.margin_*` tables (no warehouse needed), so the page does not move with the nightly build.

## Tests

`tests/margin_risk/` builds the warehouse once and checks: the concentration rule on a hand-made account; the
simulation is seeded; the planted sell-off, split and repeated file are there; the ledger adds up (equity moves
only by market P&L, deposits and interest, recomputed in pandas from the feeds and the true quantities); the risk
mart's market value, requirement and calls match a pandas recomputation from the raw feeds on all 30,720
account-days; the reconciliation flags exactly the labelled account-days; the repeated file counts once; calls
that start on a break all come from the late split, and every deposit-ended call has its deposit; P&L is
unexplained only around the two faults; and the committed results are current. `test_report.py` checks the dashboard: the new
results files are what the marts give; calls add up to the summary, sectors to the whole book each day, the
snapshot securities to their sectors and the flagged days to the planted faults; every SQL block on the page runs
against the exported tables (the day dropdown set to each snapshot) and every column a chart or table names
exists; and the rates and sell-off dates written on the page are the simulation's.
