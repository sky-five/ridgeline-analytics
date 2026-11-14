-- Why people in mature cohorts did not activate, by program, step and reason.
select
    program,
    drop_off_step,
    drop_off_reason,
    count(*) as applicants,
    count(*) / sum(count(*)) over (partition by program) as share_of_drop_offs
from {{ ref('fct_applications') }}
where is_mature and not is_activated
group by program, drop_off_step, drop_off_reason
order by program, applicants desc, drop_off_reason
