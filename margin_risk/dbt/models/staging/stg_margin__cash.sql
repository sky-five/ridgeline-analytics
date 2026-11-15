select as_of_date, account_id, cash_balance
from {{ source('raw_margin', 'cash') }}
