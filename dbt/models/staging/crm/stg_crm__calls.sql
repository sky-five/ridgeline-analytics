with source as (
    select * from {{ source('crm', 'crm_calls') }}
)

select
    call_id,
    account_id,
    rep,
    {{ to_utc('called_at') }} as called_at,
    outcome,
    cast(duration_s as {{ dbt.type_int() }}) as duration_s
from source
