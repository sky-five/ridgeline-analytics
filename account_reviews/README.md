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

## Opportunities

`opportunities.py` builds `reporting.account_opportunities` for the
[Opportunities page](../reports/pages/account-reviews/opportunities.md): paying accounts worth a call because their
measurement orders are falling or the share of homeowner leads they win has dipped. For every paying account it
reads the governed metrics `measurement_orders`, `won_leads` and `closed_leads` by account and month, then compares
the last 3 complete months with the 3 before:

- **Orders falling**: at least 6 orders in the earlier 3 months, and the last 3 months 40% or more lower.
- **Close rate dip**: at least 8 closed leads in each window, and won / closed down 15 points or more.

The floors keep small accounts from tripping a flag on a handful of rows. Accounts with both flags come first, then
by MRR; the 25 accounts that have a review page link to it. Each row carries a reason line built only from its own
window totals, for example "Measurement orders fell from 33 to 18 (-45%). Lead close rate fell from 33% (14 of 43)
to 10% (1 of 10)." On the 2026-11-10 build: 63 of 796 paying accounts flagged, 22 on orders, 42 on close rate, 1 on
both.

Limits: leads count in the month they were created, as in the governed metrics, so recent leads still open lower the
closed count but not the rate. The thresholds are fixed, not tuned per segment, and a flag says where to look, not
why.

Tests: `tests/account_reviews/test_opportunities.py` (window split, gap months, the exact 40% and 15-point edges,
the floors, the reason text, paying-only ordering and review links) and `test_account_opportunities_match_the_marts`
in `tests/test_metrics.py`, which recounts every flagged account's orders and leads from `fct_measurement_quality`
and `fct_contractor_leads` and re-applies both rules.
