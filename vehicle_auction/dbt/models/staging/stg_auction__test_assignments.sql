select
    vehicle_id,
    arm,
    cast(assigned_on as date) as assigned_on
from {{ source('raw_auction', 'test_assignments') }}
