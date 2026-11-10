# ARR and revenue recognition

Month-end numbers a finance team signs off on, built from subscription billing data, with a second independent calculation that has to agree to the cent before anything is trusted.

> **All data is synthetic.** `billing.py` generates Stripe-shaped invoices and contract changes from a fixed seed. No real company's data is used.

## The problem

ARR and revenue are often treated as the same number, but they aren't. ARR comes from the contract: what each customer is paying per month right now, times 12. Revenue comes from invoices: an annual plan paid up front in January is earned a little each day for twelve months, and the unearned part sits on the balance sheet as deferred revenue. Mid-period upgrades and refunds make both harder. These numbers are often rebuilt by hand in a spreadsheet at month end. This module builds them as SQL models and checks them against a separate Python calculation every run.

## What it builds

| Table | Grain | What it answers |
|---|---|---|
| `rev_line_months` | invoice line × month | How much of each line was earned in each month |
| `fct_revenue_monthly` | month | Recognized revenue split into subscription, proration and credit, plus future months already billed |
| `fct_deferred_revenue` | closed month | Opening + billed − recognized = closing deferred revenue |
| `customer_month_mrr` | customer × month | Contract MRR at month end |
| `fct_arr_movements` | customer × month with a change | New, reactivation, expansion, contraction or churn |
| `fct_arr_bridge` | month | Opening ARR → movements → closing ARR, and paying customers |
| `fct_arr_definitions` | closed month | Contract, billed and run-rate ARR side by side, with the items that explain the gaps |

The synthetic billing covers monthly and annual plans (annual = 10 months up front), billing in advance, prorated charges for mid-period upgrades, prorated credits for immediate cancels, seat changes and churn at renewal, and churned customers who come back on a new subscription.

## Policies, stated once

- **Ratable by day.** Revenue earned through a date = amount × days elapsed ÷ days in the service period, truncated to the cent. A month's revenue is the difference of two of those figures, so a line's months always add back to its amount exactly.
- **Churn counts in the month service stops.** A plan paid through 30 April is still ARR at the end of April.
- **Movements are per customer.** A customer who switches subscriptions is an expansion or contraction, not churn plus new. A customer who comes back after reaching zero is a reactivation, not new.

## Three ARR definitions

"ARR" is often three different numbers that a team quotes as one. `fct_arr_definitions` puts them side by side for every closed month and explains the gap between them:

| Definition | How it is built | What it is good for |
|---|---|---|
| Contract ARR | 12 × month-end contract MRR at list price | Growth and movements (the same number as `fct_arr_bridge`) |
| Billed ARR | What customers are committed to pay per year: monthly plans 12 × MRR, annual plans 10 × MRR | Cash and bookings |
| Run-rate ARR | 12 × the month's recognized revenue | What the income statement supports |

The bridge, summed per subscription:

| Item | Why it exists | Sign |
|---|---|---|
| Annual prepay discount | Annual plans pay 10 months for 12 | always negative |
| New, part month | A subscription that starts after the 1st earns only part of the month | negative |
| Ended, part month | A subscription that ends mid-month has no ARR at month end but still earned revenue that month | positive |
| Price change, part month | An upgrade mid-month counts in full in billed ARR but earns only from the upgrade date | negative |
| Calendar and rounding | Revenue is earned by day, so a 31-day month runs above 1/12 of a year and a 30-day month below; also cent truncation | follows month length |

Contract ARR + annual discount = billed ARR, and billed ARR + the four timing items = run-rate ARR, every month. Contract ARR is tied to `fct_arr_bridge` and run-rate ARR to `fct_revenue_monthly`, so the bridge is checked against two models built another way. The 10-months rule for annual plans is checked against every annual invoice (163 of them).

As of 2026-09-30 (in dollars):

```
month        contract    annual      billed       new     ended     price  calendar    run-rate
2026-08      $817,440  $-45,290    $772,150  $-27,736    $1,875  $-11,105    $4,155    $739,339
2026-09      $806,640  $-46,380    $760,260  $-18,165   $22,090   $-7,437  $-10,832    $745,916
```

September's contract ARR is $806,640, but the revenue booked that month supports $745,916, 7.5% less. Most of the gap is the annual discount. The rest is timing that changes month to month: in September more subscriptions ended mid-month (+$22,090: revenue still earned, no ARR at month end) and fewer started mid-month (−$18,165) than in August, and having 30 days cost $10,832 on the calendar line.

## The parallel run

`reference.py` computes revenue, deferred revenue and the full ARR bridge again in plain Python. It uses the same policies but different mechanics: revenue is walked one day at a time instead of joining month overlaps, and ARR is a replay of contract changes instead of an as-of join plus window functions. `parallel_run.py` compares every number and lists any that differ. A test plants a one-cent error to prove the check catches it.

This is the "run the old and new versions side by side until they match" method, used here for the calculation itself.

## Run it

```bash
.venv/Scripts/python -m revrec                    # build in memory, print the close, run the parallel check
.venv/Scripts/python -m revrec --db revrec.duckdb # keep the tables to query
.venv/Scripts/python -m pytest tests/revrec -q
```

Output as of 2026-09-30 (400 synthetic customers):

```
ARR bridge, last 6 months
month         opening       new   react.    expan.    contr.      churn     closing
2026-08      $751,920   $45,120       $0   $25,080     $-540    $-4,140    $817,440
2026-09      $817,440   $23,040   $6,180   $14,220     $-900   $-53,340    $806,640

Deferred revenue rollforward, last 6 months
month         opening      billed  recognized     closing
2026-08      $138,436     $69,215     $61,612    $146,039
2026-09      $146,039     $54,502     $62,160    $138,381

Already billed, still to be earned after 2026-09-30: $138,381

Parallel run: SQL and the Python reference agree on all 201 numbers, to the cent
```

Closing deferred revenue equals the revenue scheduled for future months, a third check, also covered by a test.

## Tests (23)

- Hand-calculated cases: an annual prepay earned by day, a refund reversing the rest of a period, a deferred-revenue rollforward, one customer moving through new → expansion → contraction → churn → reactivation, and churn landing in the month service stops.
- On the full generated data: every month's ARR bridge adds up, every rollforward balances, deferred revenue never goes negative, and total billed equals total recognized across all time, and closing deferred revenue equals the revenue still scheduled.
- The parallel run agrees on two different seeds and catches a planted one-cent error.
- ARR definitions: hand-calculated annual plan (discount and calendar effect), mid-month start, mid-month churn and mid-month upgrade; on the full generated data, the bridge closes and ties to the movement bridge and the revenue schedule in all 21 months, every annual invoice is 10 × MRR, and each item has its expected sign.

## What a production version adds

Usage-based and multi-element contracts (ASC 606 allocation across performance obligations), FX, billing in arrears (unbilled receivables), and the same models in dbt with these checks as tests. The SQL is plain DuckDB and ports to dbt without changes to the logic.
