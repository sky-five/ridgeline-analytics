# ARR and revenue recognition

Month-end numbers a finance team signs off on, built from subscription billing data, with a second independent calculation that has to agree to the cent before anything is trusted.

> **All data is synthetic.** Invoices and contract changes come from the billing pack in [saas-world-sim](https://github.com/sky-five/saas-world-sim#domain-pack-billing), generated from a fixed seed. No real company's data is used.

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

## How the data is made

- **One fixed history.** saas-world-sim's billing pack (pinned at `v0.5.0`) simulates 700 customers signing up from 2025-01-01 to 2027-12-31, once, from one seed. Each customer draws from its own keyed random stream.
- **Revealed one day per night.** `billing.py` reads `billing_as_of(date)`: invoices issued and contract changes effective by the end of that date. A line keeps its whole service period, so an annual plan paid up front shows as deferred revenue. `python -m revrec` closes the books as of yesterday (UTC) by default, and CI and the nightly job run it on the same date as the warehouse build.
- **Same date, same rows.** Two reads of one date are identical, and an earlier date is a prefix of a later one (both tested). The numbers below are pinned to the 2026-09-30 snapshot.
- **Planted patterns:** monthly plans churn at about 3.8% of renewals and annual plans at 20%; a few percent of billing periods have a mid-period upgrade or an immediate cancel with a refund; 51 of the 700 customers leave and come back on a new subscription.

The billing covers monthly and annual plans (annual = 10 months up front), billing in advance, prorated charges for mid-period upgrades, prorated credits for immediate cancels, seat changes and churn at renewal, and churned customers who come back on a new subscription.

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
| Price change, part month | A mid-month upgrade or seat change counts in full in billed ARR, but the month earned the old price until the change date | negative for an increase, positive for a decrease; net negative in every month from May 2025 |
| Calendar and rounding | Revenue is earned by day, so a 31-day month runs above 1/12 of a year and a 30-day month below; also cent truncation | follows month length |

Contract ARR + annual discount = billed ARR, and billed ARR + the four timing items = run-rate ARR, every month. Contract ARR is tied to `fct_arr_bridge` and run-rate ARR to `fct_revenue_monthly`, so the bridge is checked against two models built another way. The 10-months rule for annual plans is checked against every annual invoice (154 of them).

As of 2026-09-30 (in dollars):

```
month        contract    annual      billed       new     ended     price  calendar    run-rate
2026-08      $724,440  $-42,960    $681,480  $-23,893   $17,318   $-5,869    $3,928    $672,964
2026-09      $736,260  $-44,770    $691,490  $-22,712   $29,827   $-9,723   $-9,351    $679,531
```

September's contract ARR is $736,260, but the revenue booked that month supports $679,531, 7.7% less. Most of the gap is the annual discount ($44,770). The rest is timing that changes month to month: in September more subscriptions ended mid-month than in August (+$29,827 against +$17,318: revenue still earned, no ARR at month end), mid-month starts cost about the same (−$22,712), and having 30 days cost $9,351 on the calendar line.

## The parallel run

`reference.py` computes revenue, deferred revenue and the full ARR bridge again in plain Python. It uses the same policies but different mechanics: revenue is walked one day at a time instead of joining month overlaps, and ARR is a replay of contract changes instead of an as-of join plus window functions. `parallel_run.py` compares every number and lists any that differ. A test plants a one-cent error to prove the check catches it.

This is the "run the old and new versions side by side until they match" method, used here for the calculation itself.

## Run it

```bash
.venv/Scripts/python -m revrec                       # as of yesterday: build in memory, print the close, run the parallel check
.venv/Scripts/python -m revrec --as-of 2026-09-30    # the snapshot quoted below
.venv/Scripts/python -m revrec --db revrec.duckdb    # keep the tables to query
.venv/Scripts/python -m pytest tests/revrec -q
```

Output as of 2026-09-30 (393 of the 700 synthetic customers have signed up by then):

```
ARR bridge, last 6 months
month         opening       new   react.    expan.    contr.      churn     closing
2026-08      $687,360   $48,840   $5,280   $13,920   $-1,560   $-29,400    $724,440
2026-09      $724,440   $42,060   $2,400   $18,120   $-1,500   $-49,260    $736,260

Deferred revenue rollforward, last 6 months
month         opening      billed  recognized     closing
2026-08      $135,726     $70,537     $56,080    $150,183
2026-09      $150,183     $58,889     $56,628    $152,445

Already billed, still to be earned after 2026-09-30: $152,445

Parallel run: SQL and the Python reference agree on all 201 numbers, to the cent
```

Closing deferred revenue equals the revenue scheduled for future months, a third check, also covered by a test.

## Tests (29)

- Hand-calculated cases: an annual prepay earned by day, a refund reversing the rest of a period, a deferred-revenue rollforward, one customer moving through new → expansion → contraction → churn → reactivation, and churn landing in the month service stops.
- On the full data: every month's ARR bridge adds up, every rollforward balances, deferred revenue never goes negative, and total billed equals total recognized across all time, and closing deferred revenue equals the revenue still scheduled.
- The parallel run agrees on two different seeds and as of yesterday, and catches a planted one-cent error.
- Engine data: the same date gives the same rows, an earlier date is a prefix of a later one, and the snapshot's row counts match the numbers above.
- ARR definitions: hand-calculated annual plan (discount and calendar effect), mid-month start, mid-month churn, mid-month upgrade and mid-month seat decrease; on the full data, the bridge closes and ties to the movement bridge and the revenue schedule in all 21 months, every annual invoice is 10 × MRR, each item has its expected sign, and every mid-month decrease has a non-negative price-change item.

## What a production version adds

Usage-based and multi-element contracts (ASC 606 allocation across performance obligations), FX, billing in arrears (unbilled receivables), and the same models in dbt with these checks as tests. The SQL is plain DuckDB and ports to dbt without changes to the logic.
