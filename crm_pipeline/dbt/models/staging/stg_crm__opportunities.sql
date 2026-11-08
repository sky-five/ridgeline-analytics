select
    opportunity_id,
    account_id,
    owner_id,
    type as opportunity_type,
    lead_source,
    stage,
    amount_usd,
    probability,
    cast(close_date as date) as close_date,
    is_closed,
    is_won,
    closed_at,
    created_at
from {{ source('raw_crm', 'opportunities') }}
