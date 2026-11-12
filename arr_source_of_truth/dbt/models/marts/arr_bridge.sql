-- The ARR bridge: opening + new + reactivation + expansion + contraction + churn = closing, per month.
with totals as (
    select
        month_start,
        12 * sum(mrr_cents) as closing_arr_cents,
        count(*) filter (where mrr_cents > 0) as paying_customers
    from {{ ref('arr_customer_months') }}
    group by month_start
),

moves as (
    select
        month_start,
        sum(change_arr_cents) filter (where movement = 'new') as new_arr_cents,
        sum(change_arr_cents) filter (where movement = 'reactivation') as reactivation_arr_cents,
        sum(change_arr_cents) filter (where movement = 'expansion') as expansion_arr_cents,
        sum(change_arr_cents) filter (where movement = 'contraction') as contraction_arr_cents,
        sum(change_arr_cents) filter (where movement = 'churn') as churn_arr_cents
    from {{ ref('arr_movements') }}
    group by month_start
)

select
    m.month_start,
    cast(coalesce(lag(t.closing_arr_cents) over (order by m.month_start), 0) as bigint) as opening_arr_cents,
    cast(coalesce(mv.new_arr_cents, 0) as bigint) as new_arr_cents,
    cast(coalesce(mv.reactivation_arr_cents, 0) as bigint) as reactivation_arr_cents,
    cast(coalesce(mv.expansion_arr_cents, 0) as bigint) as expansion_arr_cents,
    cast(coalesce(mv.contraction_arr_cents, 0) as bigint) as contraction_arr_cents,
    cast(coalesce(mv.churn_arr_cents, 0) as bigint) as churn_arr_cents,
    cast(coalesce(t.closing_arr_cents, 0) as bigint) as closing_arr_cents,
    cast(coalesce(t.paying_customers, 0) as bigint) as paying_customers
from {{ ref('arr_months') }} as m
left join totals as t on m.month_start = t.month_start
left join moves as mv on m.month_start = mv.month_start
