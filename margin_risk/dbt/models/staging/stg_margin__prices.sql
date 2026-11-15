select price_date, symbol, close
from {{ source('raw_margin', 'prices') }}
