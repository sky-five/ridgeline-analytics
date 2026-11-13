-- One row per person and month end they were employed on: hired on or before it, not yet left.
-- Salary is the annual base in effect that day.
with months as (
    select last_day(m)::date as month_end
    from generate_series(
        date '2024-01-01', date_trunc('month', date '{{ var("as_of_date") }}'), interval 1 month
    ) as t (m)
),

employed as (
    select
        months.month_end,
        e.emp_id,
        e.department,
        e.location,
        e.job_level,
        e.employment_type,
        e.hire_date,
        date_diff('month', e.hire_date, months.month_end) as tenure_months
    from months
    inner join {{ ref('stg_hr__employees') }} as e
        on
            e.hire_date <= months.month_end
            and (e.term_date is null or e.term_date > months.month_end)
)

select
    employed.*,
    salary.annual_base_cents
from employed
asof left join {{ ref('stg_hr__salary_changes') }} as salary
    on
        employed.emp_id = salary.emp_id
        and employed.month_end >= salary.effective_date
