with accounts as (
    select * from {{ ref('stg_app_db__accounts') }}
),

subscriptions as (
    select * from {{ ref('stg_app_db__subscriptions') }}
),

first_paid as (
    select
        account_id,
        min(changed_at) as first_paid_at
    from {{ ref('fct_mrr_movements') }}
    where movement_type = 'new'
    group by account_id
)

select
    a.account_id,
    a.company_name,
    a.signup_at,
    cast({{ dbt.date_trunc('month', 'a.signup_at') }} as date) as signup_month,
    a.channel,
    a.campaign_id,
    a.region,
    a.crew_size,
    f.first_paid_at,
    s.plan as current_plan,
    s.addons as current_addons,
    cast(coalesce(s.mrr_usd, 0) as {{ dbt.type_numeric() }}) as current_mrr,
    coalesce(s.status = 'active', false) as is_paying,
    s.canceled_at as churned_at,
    s.cancel_reason
from accounts as a
left join subscriptions as s on a.account_id = s.account_id
left join first_paid as f on a.account_id = f.account_id
