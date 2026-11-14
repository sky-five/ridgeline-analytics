select dealer_id, region
from {{ source('raw_vehicles', 'dealers') }}
