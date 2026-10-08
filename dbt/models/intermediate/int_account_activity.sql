-- Recent activity per account, counted back from the end of the as-of day.
{% set as_of_end = as_of_end() %}

with events as (
    select
        account_id,
        sum(case when event_type = 'login' then 1 else 0 end) as logins_30d,
        sum(case when event_type = 'proposal_sent' then 1 else 0 end) as proposals_30d
    from {{ ref('stg_product_events__events') }}
    where occurred_at > {{ dbt.dateadd('day', -30, as_of_end) }}
    group by account_id
),

tickets as (
    select
        account_id,
        count(*) as tickets_90d
    from {{ ref('stg_support__tickets') }}
    where created_at > {{ dbt.dateadd('day', -90, as_of_end) }}
    group by account_id
),

redos as (
    select
        account_id,
        count(*) as redo_90d
    from {{ ref('stg_app_db__measurement_orders') }}
    where redo_requested_at > {{ dbt.dateadd('day', -90, as_of_end) }}
    group by account_id
)

select
    a.account_id,
    coalesce(e.logins_30d, 0) as logins_30d,
    coalesce(e.proposals_30d, 0) as proposals_30d,
    coalesce(t.tickets_90d, 0) as tickets_90d,
    coalesce(r.redo_90d, 0) as redo_90d
from {{ ref('stg_app_db__accounts') }} as a
left join events as e on a.account_id = e.account_id
left join tickets as t on a.account_id = t.account_id
left join redos as r on a.account_id = r.account_id
