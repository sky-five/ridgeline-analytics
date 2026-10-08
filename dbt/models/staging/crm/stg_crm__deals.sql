with source as (
    select * from {{ source('crm', 'crm_deals') }}
)

select
    deal_id,
    account_id,
    owner_rep,
    stage,
    {{ to_utc('created_at') }} as created_at,
    {{ to_utc('closed_at') }} as closed_at,
    cast(amount_usd as {{ dbt.type_numeric() }}) as amount_usd,
    {{ to_utc('updated_at') }} as updated_at
from source
