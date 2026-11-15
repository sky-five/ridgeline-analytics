-- One row per weekday: mart totals against ledger totals, and how many accounts break. A flagged day is one
-- with any break; its totals should not be reported until the break is explained.
select
    as_of_date,
    sum(mart_market_value) as mart_market_value,
    sum(ledger_market_value) as ledger_market_value,
    round(sum(market_value_diff), 2) as market_value_drift,
    sum(mart_cash_balance) as mart_cash_balance,
    sum(ledger_cash_balance) as ledger_cash_balance,
    round(sum(cash_diff), 2) as cash_drift,
    count(*) filter (where is_break) as accounts_broken,
    count(*) filter (where is_break and abs(market_value_diff) >= {{ var('recon_tolerance') }})
        as market_value_breaks,
    count(*) filter (where is_break and abs(cash_diff) >= {{ var('recon_tolerance') }}) as cash_breaks,
    bool_or(is_break) as is_flagged
from {{ ref('reconciliation_account_day') }}
group by as_of_date
