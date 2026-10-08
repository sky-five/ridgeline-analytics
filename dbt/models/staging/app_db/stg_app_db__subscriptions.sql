with source as (
    select * from {{ source('app_db', 'subscriptions') }}
)

select
    subscription_id,
    account_id,
    plan,
    status,
    addons,
    cast(mrr_usd as {{ dbt.type_numeric() }}) as mrr_usd,
    {{ to_utc('started_at') }} as started_at,
    {{ to_utc('canceled_at') }} as canceled_at,
    cancel_reason,
    {{ to_utc('updated_at') }} as updated_at
from source
