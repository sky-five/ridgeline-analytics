-- One row per policy and calendar month it was in force, up to the as-of date.
-- earned_premium: the annual premium spread evenly over the 365-day term, for the days in force that month.
with months as (
    select cast(range as date) as earned_month
    from range(date '2025-01-01', date '{{ var("as_of_date") }}' + interval 1 day, interval 1 month)
),

overlap as (
    select
        p.policy_id,
        m.earned_month,
        p.annual_premium,
        greatest(p.start_date, m.earned_month) as first_day,
        least(
            p.end_date,
            cast(m.earned_month + interval 1 month - interval 1 day as date),
            date '{{ var("as_of_date") }}'
        ) as last_day
    from {{ ref('dim_policy') }} as p
    inner join months as m
        on
            p.start_date < m.earned_month + interval 1 month
            and p.end_date >= m.earned_month
)

select
    policy_id || '-' || strftime(earned_month, '%Y-%m') as policy_month_id,
    policy_id,
    earned_month,
    datediff('day', first_day, last_day) + 1 as earned_days,
    annual_premium * (datediff('day', first_day, last_day) + 1) / 365.0 as earned_premium
from overlap
where last_day >= first_day
