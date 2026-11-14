select program_id, program_type, eligible_segment, start_date, end_date, eligibility, is_customer_cash
from {{ ref('stg_vehicles__programs') }}
