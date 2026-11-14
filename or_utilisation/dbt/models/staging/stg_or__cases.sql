select
    case_id,
    block_id,
    room_id,
    cast(case_date as date) as case_date,
    service_id,
    booked_minutes,
    status,
    cast(wheels_in as timestamp) as wheels_in,
    cast(wheels_out as timestamp) as wheels_out
from {{ source('raw_or', 'cases') }}
