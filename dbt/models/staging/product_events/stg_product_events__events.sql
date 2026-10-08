with source as (
    select * from {{ source('product_events', 'events') }}
)

select
    event_id,
    account_id,
    event_type,
    {{ to_utc('occurred_at') }} as occurred_at,
    {{ json_number('properties', 'value_usd') }} as value_usd
from source
