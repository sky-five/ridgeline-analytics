select application_id, sale_id, program_id, cast(amount as decimal(12, 2)) as amount
from {{ source('raw_vehicles', 'incentives') }}
