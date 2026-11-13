-- The one table the governed metrics read: month end x department x location x job level, every group in
-- every month (zeros where nobody was there), so trailing 12-month windows and roll-forwards line up.
with months as (
    select distinct month_end from {{ ref('hr_employee_months') }}
),

groups as (
    select distinct department, location, job_level from {{ ref('stg_hr__employees') }}
),

active as (
    select
        month_end,
        department,
        location,
        job_level,
        count(*) as headcount,
        count(*) filter (where employment_type = 'full_time') as full_time_headcount,
        sum(tenure_months) as tenure_months_sum,
        sum(annual_base_cents) as annual_base_cents_sum
    from {{ ref('hr_employee_months') }}
    group by all
),

hires as (
    select
        last_day(hire_date) as month_end,
        department,
        location,
        job_level,
        count(*) as hires
    from {{ ref('stg_hr__employees') }}
    group by all
),

leavers as (
    select
        last_day(term_date) as month_end,
        department,
        location,
        job_level,
        count(*) as terminations,
        count(*) filter (where term_reason = 'voluntary') as voluntary_terminations
    from {{ ref('stg_hr__employees') }}
    where term_date is not null
    group by all
),

pay as (
    select
        p.pay_date as month_end,
        e.department,
        e.location,
        e.job_level,
        count(distinct p.emp_id) as paid_employees,
        sum(p.amount_cents) filter (where p.pay_type = 'base') as base_pay_cents,
        sum(p.amount_cents) filter (where p.pay_type = 'overtime') as overtime_pay_cents,
        sum(p.amount_cents) filter (where p.pay_type = 'bonus') as bonus_pay_cents,
        sum(p.amount_cents) as gross_pay_cents
    from {{ ref('stg_payroll__pay_lines') }} as p
    inner join {{ ref('stg_hr__employees') }} as e on p.emp_id = e.emp_id
    group by all
),

grid as (
    select
        months.month_end,
        groups.department,
        groups.location,
        groups.job_level,
        coalesce(active.headcount, 0) as headcount,
        coalesce(active.full_time_headcount, 0) as full_time_headcount,
        coalesce(hires.hires, 0) as hires,
        coalesce(leavers.terminations, 0) as terminations,
        coalesce(leavers.voluntary_terminations, 0) as voluntary_terminations,
        coalesce(active.tenure_months_sum, 0) as tenure_months_sum,
        coalesce(active.annual_base_cents_sum, 0) as annual_base_cents_sum,
        coalesce(pay.paid_employees, 0) as paid_employees,
        coalesce(pay.base_pay_cents, 0) as base_pay_cents,
        coalesce(pay.overtime_pay_cents, 0) as overtime_pay_cents,
        coalesce(pay.bonus_pay_cents, 0) as bonus_pay_cents,
        coalesce(pay.gross_pay_cents, 0) as gross_pay_cents
    from months
    cross join groups
    left join active using (month_end, department, location, job_level)
    left join hires using (month_end, department, location, job_level)
    left join leavers using (month_end, department, location, job_level)
    left join pay using (month_end, department, location, job_level)
)

select
    *,
    sum(terminations) over trailing_year as terminations_12m,
    sum(headcount) over trailing_year / 12.0 as avg_headcount_12m,
    count(*) over trailing_year as months_in_window
from grid
window trailing_year as (
    partition by department, location, job_level
    order by month_end
    rows between 11 preceding and current row
)
