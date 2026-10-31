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

The synthetic billing covers monthly and annual plans (annual = 10 months up front), billing in advance, prorated charges for mid-period upgrades, prorated credits for immediate cancels, seat changes and churn at renewal, and churned customers who come back on a new subscription.

## Policies, stated once

- **Ratable by day.** Revenue earned through a date = amount × days elapsed ÷ days in the service period, truncated to the cent. A month's revenue is the difference of two of those figures, so a line's months always add back to its amount exactly.
- **Churn counts in the month service stops.** A plan paid through 30 April is still ARR at the end of April.
- **Movements are per customer.** A customer who switches subscriptions is an expansion or contraction, not churn plus new. A customer who comes back after reaching zero is a reactivation, not new.

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

## Tests (16)

- Hand-calculated cases: an annual prepay earned by day, a refund reversing the rest of a period, a deferred-revenue rollforward, one customer moving through new → expansion → contraction → churn → reactivation, and churn landing in the month service stops.
- On the full generated data: every month's ARR bridge adds up, every rollforward balances, deferred revenue never goes negative, and total billed equals total recognized across all time, and closing deferred revenue equals the revenue still scheduled.
- The parallel run agrees on two different seeds and catches a planted one-cent error.

## What a production version adds

Usage-based and multi-element contracts (ASC 606 allocation across performance obligations), FX, billing in arrears (unbilled receivables), and the same models in dbt with these checks as tests. The SQL is plain DuckDB and ports to dbt without changes to the logic.
