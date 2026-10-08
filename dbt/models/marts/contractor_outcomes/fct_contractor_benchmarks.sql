-- Each contractor's month vs peers with the same crew size. Small months (< 5 leads) get no percentile.
with monthly as (
    select
        l.account_id,
        l.created_month as month,  -- noqa: RF04
        a.crew_size,
        a.region,
        count(*) as leads,
        sum(case when l.outcome_group <> 'open' then 1 else 0 end) as closed,
        sum(case when l.outcome_group = 'won' then 1 else 0 end) as won,
        median(l.speed_to_lead_min) as median_speed_min
    from {{ ref('fct_contractor_leads') }} as l
    inner join {{ ref('dim_accounts') }} as a on l.account_id = a.account_id
    group by l.account_id, l.created_month, a.crew_size, a.region
),

rated as (
    select
        *,
        cast(won as double) / nullif(closed, 0) as close_rate,
        leads >= 5 and closed > 0 as is_rankable
    from monthly
)

select
    account_id,
    month,
    crew_size,
    region,
    cast(leads as {{ dbt.type_bigint() }}) as leads,
    cast(closed as {{ dbt.type_bigint() }}) as closed,
    cast(won as {{ dbt.type_bigint() }}) as won,
    close_rate,
    cast(median_speed_min as double) as median_speed_min,
    case
        when is_rankable
            then percent_rank() over (partition by crew_size, month, is_rankable order by close_rate)
    end as close_rate_pctile,
    case
        when is_rankable
            then percent_rank() over (partition by crew_size, month, is_rankable order by median_speed_min desc)
    end as speed_pctile
from rated
