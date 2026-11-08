-- Of the closed deals that reached each stage, how many moved on and how many were won.
-- Closed deals only, so deals still in flight do not drag the rates down.
with reached as (
    select
        h.opportunity_id,
        max(h.open_stage_rank) as max_open_rank,
        bool_or(h.stage = 'closed_won') as is_won
    from {{ ref('stg_crm__opportunity_history') }} as h
    inner join {{ ref('stg_crm__opportunities') }} as o on h.opportunity_id = o.opportunity_id
    where o.is_closed
    group by h.opportunity_id
),

stages as (
    select * from (
        values (1, 'prospecting'), (2, 'qualification'), (3, 'demo'), (4, 'proposal'), (5, 'negotiation')
    ) as s (stage_rank, stage)
)

select
    s.stage_rank,
    s.stage,
    count(*) filter (where r.max_open_rank >= s.stage_rank or r.is_won) as deals_reached,
    count(*) filter (where r.max_open_rank >= s.stage_rank + 1 or r.is_won) as deals_moved_on,
    count(*) filter (where r.is_won) as deals_won,
    round(deals_moved_on / nullif(deals_reached, 0), 3) as conversion_to_next,
    round(deals_won / nullif(deals_reached, 0), 3) as win_rate_from_stage
from stages as s
cross join reached as r
group by s.stage_rank, s.stage
order by s.stage_rank
