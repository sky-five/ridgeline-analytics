-- Money is decimal throughout, so sums do not depend on the order threads add them up.
select price_date, symbol, close::decimal(18, 2) as close
from {{ source('raw_margin', 'prices') }}
