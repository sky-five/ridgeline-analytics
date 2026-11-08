-- One row per deal, rolled up to the deduplicated account and dated by when it really closed.
with opps as (
    select * from {{ ref('stg_crm__opportunities') }}
),

pushes as (
    select opportunity_id, count(*) as close_date_pushes
    from {{ ref('stg_crm__opportunity_history') }}
    where change_type = 'close_date_push'
    group by opportunity_id
)

select
    o.opportunity_id,
    d.canonical_account_id as account_id,
    o.account_id as recorded_account_id,
    a.segment,
    o.owner_id,
    o.opportunity_type,
    o.lead_source,
    o.stage,
    o.amount_usd,
    o.probability,
    o.is_closed,
    o.is_won,
    o.created_at,
    c.recorded_close_date,
    c.corrected_close_date,
    c.is_backdated,
    coalesce(p.close_date_pushes, 0) as close_date_pushes,
    case when o.is_closed then date_diff('day', cast(o.created_at as date), c.closed_on) end as days_to_close
from opps as o
inner join {{ ref('int_account_dedupe') }} as d on o.account_id = d.account_id
inner join {{ ref('stg_crm__accounts') }} as a on d.canonical_account_id = a.account_id
inner join {{ ref('int_opportunity_close_dates') }} as c on o.opportunity_id = c.opportunity_id
left join pushes as p on o.opportunity_id = p.opportunity_id
