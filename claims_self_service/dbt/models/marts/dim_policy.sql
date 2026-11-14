-- One row per policy: the dimensions every claim and premium row is sliced by.
select
    policy_id,
    line_of_business,
    region,
    channel,
    start_date,
    end_date,
    annual_premium
from {{ ref('stg_claims__policies') }}
