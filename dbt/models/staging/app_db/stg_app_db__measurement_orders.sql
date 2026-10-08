with source as (
    select * from {{ source('app_db', 'measurement_orders') }}
)

select
    order_id,
    account_id,
    {{ to_utc('ordered_at') }} as ordered_at,
    {{ to_utc('delivered_at') }} as delivered_at,
    tier,
    cast(price_usd as {{ dbt.type_numeric() }}) as price_usd,
    roof_type,
    {{ to_utc('redo_requested_at') }} as redo_requested_at,
    redo_reason,
    {{ to_utc('updated_at') }} as updated_at
from source
