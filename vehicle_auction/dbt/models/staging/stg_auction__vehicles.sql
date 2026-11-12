select
    vehicle_id,
    seller_id,
    segment,
    model_year,
    mileage,
    condition_grade,
    book_value_usd,
    cast(consigned_on as date) as consigned_on,
    channel
from {{ source('raw_auction', 'vehicles') }}
