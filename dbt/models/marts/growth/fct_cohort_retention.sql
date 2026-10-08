-- Paid cohorts by first paid month: accounts and MRR still active N months later.
{% set start_date = "cast('" ~ var('history_start_date') ~ "' as date)" %}

with movements as (
    select
        account_id,
        changed_at,
        mrr_delta
    from {{ ref('fct_mrr_movements') }}
),

cohorts as (
    select
        account_id,
        cast({{ dbt.date_trunc('month', 'first_paid_at') }} as date) as cohort_month
    from {{ ref('dim_accounts') }}
    where first_paid_at is not null
),

months as (
    {{ dbt_utils.date_spine(
        datepart="month",
        start_date=start_date,
        end_date=dbt.dateadd('month', 1, dbt.date_trunc('month', as_of_date()))
    ) }}
),

account_months as (
    select
        c.account_id,
        c.cohort_month,
        {{ dbt.datediff('c.cohort_month', 'cast(m.date_month as date)', 'month') }} as months_since_start,  -- noqa: LT05
        {{ dbt.dateadd('month', 1, 'cast(m.date_month as timestamp)') }} as next_month_start
    from cohorts as c
    inner join months as m on cast(m.date_month as date) >= c.cohort_month
),

account_month_mrr as (
    select
        am.account_id,
        am.cohort_month,
        am.months_since_start,
        coalesce(sum(mv.mrr_delta), 0) as mrr
    from account_months as am
    left join movements as mv
        on am.account_id = mv.account_id and am.next_month_start > mv.changed_at and mv.changed_at <= {{ as_of_end() }}
    group by am.account_id, am.cohort_month, am.months_since_start
),

with_start as (
    select
        *,
        first_value(mrr) over (partition by account_id order by months_since_start) as start_mrr
    from account_month_mrr
)

select
    cohort_month,
    cast(months_since_start as {{ dbt.type_int() }}) as months_since_start,
    cast(count(*) as {{ dbt.type_bigint() }}) as cohort_accounts,
    cast(sum(case when mrr > 0 then 1 else 0 end) as {{ dbt.type_bigint() }}) as retained_accounts,
    cast(sum(start_mrr) as {{ dbt.type_numeric() }}) as cohort_start_mrr,
    cast(sum(mrr) as {{ dbt.type_numeric() }}) as retained_mrr,
    cast(sum(case when mrr > 0 then 1 else 0 end) as double) / count(*) as logo_retention,
    cast(sum(mrr) as double) / nullif(sum(start_mrr), 0) as nrr,
    cast(sum(least(mrr, start_mrr)) as double) / nullif(sum(start_mrr), 0) as grr
from with_start
group by cohort_month, months_since_start
