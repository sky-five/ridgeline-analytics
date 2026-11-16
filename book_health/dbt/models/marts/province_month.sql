-- One row per province and month: growth (in force and written premium against the same month a year earlier),
-- loss ratio (incurred by loss month over earned premium) and retention (renewed over renewals due).
with p as (
    select
        month_start,
        province,
        sum(policies_in_force) as policies_in_force,
        sum(new_policies) as new_policies,
        sum(written_premium) as written_premium,
        sum(earned_premium) as earned_premium,
        sum(claims) as claims,
        sum(incurred) as incurred,
        sum(renewals_due) as renewals_due,
        sum(renewed) as renewed,
        sum(sum_rate_change) as sum_rate_change
    from {{ ref('fct_segment_month') }}
    group by all
)

select
    month_start,
    province,
    policies_in_force,
    new_policies,
    written_premium,
    earned_premium,
    claims,
    incurred,
    renewals_due,
    renewed,
    round(incurred / nullif(earned_premium, 0), 4)::double as loss_ratio,
    round(renewed / nullif(renewals_due, 0), 4)::double as retention,
    round(sum_rate_change / nullif(renewals_due, 0), 4)::double as mean_rate_change,
    round(
        policies_in_force / nullif(lag(policies_in_force, 12) over w, 0) - 1, 4
    )::double as in_force_growth_yoy,
    round(
        sum(written_premium) over w12 / nullif(sum(written_premium) over w12_before, 0) - 1, 4
    )::double as written_premium_growth_12m
from p
window
    w as (partition by province order by month_start),
    w12 as (partition by province order by month_start rows between 11 preceding and current row),
    w12_before as (partition by province order by month_start rows between 23 preceding and 12 preceding)
