select
    listing_id,
    vehicle_id,
    cast(sale_date as date) as sale_date,
    run_number,
    channel,
    reserve_usd,
    status,
    sold_price_usd
from {{ source('raw_auction', 'listings') }}
