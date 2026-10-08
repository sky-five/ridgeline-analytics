-- What each account did in its first 14 days, before paying. These are the early signals for activation
-- and scoring. The window ends at the first payment if that comes sooner, so paid-plan usage can't leak
-- the outcome into the signals.
with first_paid as (
    select
        account_id,
        min(changed_at) as first_paid_at
    from {{ ref('stg_app_db__subscription_changes') }}
    where change_type = 'new'
    group by account_id
),

accounts as (
    select
        a.account_id,
        a.signup_at,
        case
            when f.first_paid_at < {{ dbt.dateadd('day', 14, 'a.signup_at') }} then f.first_paid_at
            else {{ dbt.dateadd('day', 14, 'a.signup_at') }}
        end as window_end_at
    from {{ ref('stg_app_db__accounts') }} as a
    left join first_paid as f on a.account_id = f.account_id
),

early as (
    select
        e.account_id,
        e.event_type,
        e.occurred_at,
        a.signup_at
    from {{ ref('stg_product_events__events') }} as e
    inner join accounts as a on e.account_id = a.account_id
    where e.occurred_at < a.window_end_at
)

select
    a.account_id,
    sum(case when e.event_type = 'login' then 1 else 0 end) as logins_14d,
    sum(case when e.event_type = 'measurement_ordered' then 1 else 0 end) as measurements_14d,
    sum(case when e.event_type = 'proposal_sent' then 1 else 0 end) as proposals_14d,
    sum(case when e.event_type = 'proposal_signed' then 1 else 0 end) as signed_14d,
    count(distinct cast(e.occurred_at as date)) as active_days_14d,
    coalesce(max(
        case
            when e.event_type = 'proposal_sent' and e.occurred_at < {{ dbt.dateadd('day', 7, 'e.signup_at') }}
                then 1
            else 0
        end
    ) = 1, false) as proposal_wk1
from accounts as a
left join early as e on a.account_id = e.account_id
group by a.account_id
