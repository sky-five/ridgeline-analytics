select
    as_of_date,
    account_id,
    market_value::decimal(18, 2) as market_value,
    cash_balance::decimal(18, 2) as cash_balance
from {{ source('raw_margin', 'ledger') }}
