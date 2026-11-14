-- The mature weeks add up to the program funnel.
with weeks as (
    select program, sum(applicants) as started, sum(activated) as activated
    from {{ ref('funnel_weekly') }}
    where is_mature
    group by program
)

select weeks.program
from weeks
inner join {{ ref('funnel_by_program') }} as p on weeks.program = p.program
where weeks.started != p.started or weeks.activated != p.activated
