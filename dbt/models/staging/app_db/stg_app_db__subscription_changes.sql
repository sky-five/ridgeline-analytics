with source as (
    select * from {{ source('app_db', 'subscription_changes') }}
)

select
    change_id,
    subscription_id,
    account_id,
    {{ to_utc('changed_at') }} as changed_at,
    change_type,
    plan_after,
    addons_after,
    cast(mrr_before as {{ dbt.type_numeric() }}) as mrr_before,
    cast(mrr_after as {{ dbt.type_numeric() }}) as mrr_after,
    cancel_reason
from source
