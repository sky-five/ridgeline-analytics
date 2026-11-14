select
    program_id,
    program_type,
    segment as eligible_segment,
    cast(start_date as date) as start_date,
    cast(end_date as date) as end_date,
    eligibility,
    -- apr_subvention and lease_support pay the lender, so they never come off the price
    program_type in ('cash_rebate', 'loyalty', 'ev_bonus', 'quarter_end_cash') as is_customer_cash
from {{ source('raw_vehicles', 'programs') }}
