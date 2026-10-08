-- Company MRR every day: daily movements, then a running total.
with days as (
    {{ dbt_utils.date_spine(
        datepart="day",
        start_date="cast('" ~ var('history_start_date') ~ "' as date)",
        end_date=dbt.dateadd('day', 1, as_of_date())
    ) }}
),

movements as (
    select
        movement_date,
        sum(case when movement_type = 'new' then mrr_delta else 0 end) as new_mrr,
        sum(case when movement_type = 'expansion' then mrr_delta else 0 end) as expansion_mrr,
        sum(case when movement_type = 'contraction' then mrr_delta else 0 end) as contraction_mrr,
        sum(case when movement_type = 'churn' then mrr_delta else 0 end) as churned_mrr,
        sum(case when movement_type = 'reactivation' then mrr_delta else 0 end) as reactivation_mrr,
        sum(case when movement_type in ('new', 'reactivation') then 1 when movement_type = 'churn' then -1 else 0 end)
            as net_new_accounts
    from {{ ref('fct_mrr_movements') }}
    group by movement_date
),

daily as (
    select
        cast(d.date_day as date) as date_day,
        coalesce(m.new_mrr, 0) as new_mrr,
        coalesce(m.expansion_mrr, 0) as expansion_mrr,
        coalesce(m.contraction_mrr, 0) as contraction_mrr,
        coalesce(m.churned_mrr, 0) as churned_mrr,
        coalesce(m.reactivation_mrr, 0) as reactivation_mrr,
        coalesce(m.net_new_accounts, 0) as net_new_accounts
    from days as d
    left join movements as m on cast(d.date_day as date) = m.movement_date
)

select
    date_day,
    cast(
        sum(new_mrr + expansion_mrr + contraction_mrr + churned_mrr + reactivation_mrr)
            over (order by date_day rows between unbounded preceding and current row)
        as {{ dbt.type_numeric() }}
    ) as mrr,
    cast(
        sum(net_new_accounts) over (order by date_day rows between unbounded preceding and current row)
        as {{ dbt.type_bigint() }}
    ) as paying_accounts,
    cast(new_mrr as {{ dbt.type_numeric() }}) as new_mrr,
    cast(expansion_mrr as {{ dbt.type_numeric() }}) as expansion_mrr,
    cast(contraction_mrr as {{ dbt.type_numeric() }}) as contraction_mrr,
    cast(churned_mrr as {{ dbt.type_numeric() }}) as churned_mrr,
    cast(reactivation_mrr as {{ dbt.type_numeric() }}) as reactivation_mrr,
    cast(new_mrr + expansion_mrr + contraction_mrr + churned_mrr + reactivation_mrr as {{ dbt.type_numeric() }})
        as net_new_mrr
from daily
