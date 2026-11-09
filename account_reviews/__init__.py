"""Account reviews: one page template, many accounts.

Builds the two tables the Evidence template `reports/pages/account-reviews/[account_id].md` reads, for the
largest paying accounts: a header row per account (from the health mart) and a 12-month series per account
(from the governed metrics, grouped by the `account` entity). Every number on a review page comes from the
same MetricFlow definitions as the company-wide pages.
"""
