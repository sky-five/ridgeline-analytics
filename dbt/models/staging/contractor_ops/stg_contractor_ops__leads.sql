with source as (
    select * from {{ source('contractor_ops', 'contractor_leads') }}
)

select
    lead_id,
    account_id,
    source as lead_source,
    {{ to_utc('created_at') }} as created_at,
    {{ to_utc('first_contact_at') }} as first_contact_at,
    {{ to_utc('inspection_at') }} as inspection_at,
    {{ to_utc('proposal_sent_at') }} as proposal_sent_at,
    {{ to_utc('closed_at') }} as closed_at,
    outcome,
    cast(proposal_value_usd as {{ dbt.type_numeric() }}) as proposal_value_usd,
    {{ to_utc('updated_at') }} as updated_at
from source
