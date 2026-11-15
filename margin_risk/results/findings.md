# Margin book: findings

Simulated data. 240 accounts (181 allowed to borrow), 128 weekdays from 2026-01-02 to 2026-06-30.

## The book on 2026-06-30

- 179 borrowers owe $14,116,049 against $38,078,684 of securities in the whole book; equity $24,402,326.
- Collateral coverage (market value less each holding's maintenance requirement, over the loan) is 1.58; borrowers use 90.6% of what they could borrow at the 50% initial rate.
- 42 borrowers hold over half their account in one security. The largest single holding behind the loans is SOF02 (software, 7.1% of borrowers' securities); semiconductors as a sector is 19.3%.

## Margin calls

- 2026-03-16 to 2026-03-20: semiconductors fell 26.7% to 35.7%; market P&L for the week $-2,902,481. 10 calls started that week or the next.
- 62 real calls over the period (62 in concentrated accounts, 62 with a semiconductor as the largest holding), $91,566 short on the day of the call, median 2 weekday(s) in call. Ended by deposit 18, liquidation 24, the market 19, still open 1.
- 7 more calls start on an account-day that does not reconcile to the ledger. They are not real (see below) and are left out of the numbers above.

## Does the mart agree with the ledger

The reconciliation compares 30,720 account-days of mart market value and cash with the books of record and flags 252 of them, on 2 days. Against what was planted: 0 missed, 0 false alarms.

| day | market value drift | cash drift | accounts | cause |
|---|---:|---:|---:|---|
| 2026-04-15 | $-418,103 | $0 | 77 | positions file still has SEM03's pre-split quantity on its ex-date |
| 2026-05-29 | $0 | $80,589 | 175 | May's margin interest is in the ledger but not in the cash file |

- The positions file for 2026-02-11 was loaded 2 times (3,594 rows for 1,797 holdings). Staging keeps the latest load; counted twice the day would be $35,103,999 over the ledger.
- Daily P&L leaves equity unexplained on 2026-04-15, 2026-04-16, 2026-05-29, 2026-06-01: each fault shows on its own day and again, reversed, the next. The P&L check only says something moved; the ledger says which day is wrong.
