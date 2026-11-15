select as_of_date, account_id, cash_balance::decimal(18, 2) as cash_balance
from {{ source('raw_margin', 'cash') }}
