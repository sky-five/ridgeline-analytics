select
    policy_id,
    line_of_business,
    region,
    channel,
    cast(start_date as date) as start_date,
    cast(end_date as date) as end_date,
    cast(annual_premium as decimal(12, 2)) as annual_premium
from {{ source('raw_claims', 'policies') }}
