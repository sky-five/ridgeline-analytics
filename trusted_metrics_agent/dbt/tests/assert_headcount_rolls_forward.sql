-- Each group's headcount = last month's + hires - leavers (people never change group).
select department, location, job_level, month_end
from (
    select
        *,
        lag(headcount) over (partition by department, location, job_level order by month_end) as prev_headcount
    from {{ ref('hr_group_months') }}
)
where prev_headcount is not null and headcount <> prev_headcount + hires - terminations
