-- The weekly mart and the period mart count the same minutes.
with weekly as (
    select period, sum(allocated_minutes) as allocated, sum(owner_in_block_minutes) as owner_minutes,
        sum(reused_in_block_minutes) as reused, sum(completed_cases) as cases
    from {{ ref('utilisation_weekly') }}
    group by period
)

select w.period
from weekly as w
inner join {{ ref('utilisation_by_period') }} as p on w.period = p.period and p.blocks_in_scope = 'all'
where w.allocated <> p.allocated_minutes or w.owner_minutes <> p.owner_in_block_minutes
    or w.reused <> p.reused_in_block_minutes or w.cases <> p.completed_cases
