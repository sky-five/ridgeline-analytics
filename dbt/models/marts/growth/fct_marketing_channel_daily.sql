-- Per channel per day: spend, signups, and the paid conversions those signups produced.
-- CAC only uses signup cohorts whose 60-day outcome is known: the window ends cac_lag_days before the day.
{% set start_date = "cast('" ~ var('history_start_date') ~ "' as date)" %}
{% set lag = var('cac_lag_days') | int %}
{% set frame = "rows between " ~ (lag + (var('cac_window_days') | int) - 1) ~ " preceding and " ~ lag ~ " preceding" %}

with days as (
    {{ dbt_utils.date_spine(datepart="day", start_date=start_date, end_date=dbt.dateadd('day', 1, as_of_date())) }}
),

channels as (
    select distinct channel from {{ ref('fct_account_funnel') }}
),

spend as (
    select
        spend_date,
        channel,
        sum(spend_usd) as spend_usd
    from {{ ref('stg_ads__ad_spend') }}
    group by spend_date, channel
),

signups as (
    select
        cast(signup_at as date) as signup_date,
        channel,
        count(*) as signups,
        sum(case when is_paid_60d then 1 else 0 end) as paid_60d_from_cohort
    from {{ ref('fct_account_funnel') }}
    group by cast(signup_at as date), channel
),

daily as (
    select
        c.channel,
        cast(d.date_day as date) as date_day,
        coalesce(sp.spend_usd, 0) as spend_usd,
        coalesce(su.signups, 0) as signups,
        coalesce(su.paid_60d_from_cohort, 0) as paid_60d_from_cohort
    from days as d
    cross join channels as c
    left join spend as sp on cast(d.date_day as date) = sp.spend_date and c.channel = sp.channel
    left join signups as su on cast(d.date_day as date) = su.signup_date and c.channel = su.channel
),

windowed as (
    select
        *,
        sum(spend_usd) over (partition by channel order by date_day {{ frame }}) as spend_window,
        sum(paid_60d_from_cohort) over (partition by channel order by date_day {{ frame }}) as paid_window
    from daily
)

select
    date_day,
    channel,
    cast(spend_usd as {{ dbt.type_numeric() }}) as spend_usd,
    cast(signups as {{ dbt.type_bigint() }}) as signups,
    cast(paid_60d_from_cohort as {{ dbt.type_bigint() }}) as paid_60d_from_cohort,
    cast(spend_window / nullif(paid_window, 0) as {{ dbt.type_numeric() }}) as cac_usd
from windowed
