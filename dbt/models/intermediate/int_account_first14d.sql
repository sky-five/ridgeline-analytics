-- What each account did in its first 14 days. These are the early signals for activation and scoring.
with accounts as (
    select
        account_id,
        signup_at
    from {{ ref('stg_app_db__accounts') }}
),

early as (
    select
        e.account_id,
        e.event_type,
        e.occurred_at,
        a.signup_at
    from {{ ref('stg_product_events__events') }} as e
    inner join accounts as a on e.account_id = a.account_id
    where e.occurred_at < {{ dbt.dateadd('day', 14, 'a.signup_at') }}
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
