select
    service_id,
    mean_booked_minutes
from {{ source('raw_or', 'services') }}
