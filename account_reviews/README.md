# Account reviews

One page template, many accounts. `reviews.py` picks the 25 largest paying accounts by current MRR and builds the
two tables the Evidence template [reports/pages/account-reviews/[account_id].md](../reports/pages/account-reviews/%5Baccount_id%5D.md)
reads:

- `reporting.account_review`: one row per account with plan, region, crew size, MRR, health score and band, and
  plain talking points built only from numbers shown on the same page.
- `reporting.account_review_monthly`: the last 12 complete months per account. The figures are the governed
  metrics `net_new_mrr`, `tickets`, `measurement_orders`, `redo_orders`, `leads`, `won_leads` and `closed_leads`,
  queried through MetricFlow grouped by the `account` entity. Month-end MRR is the running sum of `net_new_mrr`
  from the account's first month on record. Months with no activity count as zero.

`scripts/export_reporting.py` writes both tables during the nightly build. The index page links every reviewed
account so Evidence prerenders one static page each.

Tests: `tests/account_reviews/` (the pick, gap months, the running sum, the talking points; no warehouse needed) and
`test_account_reviews_match_the_marts` in `tests/test_metrics.py` (month-end MRR against `fct_mrr_movements`,
tickets against `fct_support_tickets`, for all 25 accounts). All data is simulated.

## Checked summary

Each review opens with a short written summary drafted by `narrative.py` from the same monthly table: MRR now
against twelve months ago, the largest monthly MRR change, leads closed and won in the last 3 months against the 3
before, measurement redos, support tickets, health score.

`check(text, header, series)` reads any text, drafted here, edited by hand or written by a model, and finds every
dollar amount, percentage, count, month and "N months" in it. Each must equal a value computed from the review
tables, at the precision the text shows (`67%` passes for 10 of 15, `66%` does not), and only facts on its
sentence's topic count (a sentence about tickets can't quote a lead count). Months must fall inside the review
window. `review_tables` raises if a summary fails, so the nightly build stops rather than publish a wrong number;
the page shows how many numbers were checked. On the 2026-11-09 build that was 516 numbers across the 25 summaries,
18 to 23 each.

Limits, pinned in the tests: it checks values, not wording, so "up" vs "down" is not read, and a month is held to
the window rather than paired with the number next to it. A number that happens to equal another fact on the same
topic passes.

Tests: `tests/account_reviews/test_narrative.py` (the drafted text for a fixed series; edited amounts, percentages,
counts, months and windows fail; topics; precision) and `test_account_review_summaries_check_against_the_warehouse`
in `tests/test_metrics.py`, which re-checks all 25 published summaries against the tables as stored.
