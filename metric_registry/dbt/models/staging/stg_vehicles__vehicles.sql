select vehicle_id, segment, cast(msrp as decimal(12, 2)) as msrp
from {{ source('raw_vehicles', 'vehicles') }}
