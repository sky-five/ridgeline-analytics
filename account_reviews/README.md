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
