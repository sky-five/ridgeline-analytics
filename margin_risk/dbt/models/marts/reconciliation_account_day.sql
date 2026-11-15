-- The marts against the books of record, per account and day. A break is a difference of at least the
-- tolerance in market value or cash.
select
    l.as_of_date,
    l.account_id,
    coalesce(a.market_value, 0) as mart_market_value,
    l.market_value as ledger_market_value,
    round(coalesce(a.market_value, 0) - l.market_value, 2) as market_value_diff,
    a.cash_balance as mart_cash_balance,
    l.cash_balance as ledger_cash_balance,
    round(coalesce(a.cash_balance, 0) - l.cash_balance, 2) as cash_diff,
    a.account_id is null as missing_from_mart,
    a.account_id is null
    or abs(coalesce(a.market_value, 0) - l.market_value) >= {{ var('recon_tolerance') }}
    or abs(coalesce(a.cash_balance, 0) - l.cash_balance) >= {{ var('recon_tolerance') }} as is_break
from {{ ref('stg_margin__ledger') }} as l
left join {{ ref('fct_account_day') }} as a on l.as_of_date = a.as_of_date and l.account_id = a.account_id
