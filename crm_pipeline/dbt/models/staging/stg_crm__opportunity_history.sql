select
    history_id,
    opportunity_id,
    changed_at,
    stage,
    case stage
        when 'prospecting' then 1
        when 'qualification' then 2
        when 'demo' then 3
        when 'proposal' then 4
        when 'negotiation' then 5
    end as open_stage_rank,  -- null once closed
    stage in ('closed_won', 'closed_lost') as is_closed,
    amount_usd,
    cast(close_date as date) as close_date,
    probability,
    change as change_type
from {{ source('raw_crm', 'opportunity_history') }}
