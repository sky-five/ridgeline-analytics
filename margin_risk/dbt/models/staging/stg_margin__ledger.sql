select as_of_date, account_id, market_value, cash_balance
from {{ source('raw_margin', 'ledger') }}
