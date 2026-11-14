select
    block_id,
    cast(block_date as date) as block_date,
    room_id,
    service_id as owner_service_id,
    cast(starts_at as timestamp) as starts_at,
    cast(ends_at as timestamp) as ends_at,
    datediff('minute', cast(starts_at as timestamp), cast(ends_at as timestamp)) as allocated_minutes
from {{ source('raw_or', 'blocks') }}
