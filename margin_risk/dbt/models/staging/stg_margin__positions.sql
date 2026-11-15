-- One row per account, security and day: a file loaded more than once keeps its latest load.
select as_of_date, account_id, symbol, quantity, file_name, loaded_at
from {{ source('raw_margin', 'positions') }}
qualify row_number() over (partition by as_of_date, account_id, symbol order by loaded_at desc) = 1
