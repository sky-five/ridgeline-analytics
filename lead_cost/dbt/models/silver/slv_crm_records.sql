-- The current version of every CRM record (the last row delivered for its crm_id), identifiers cleaned.
select
    crm_id,
    client,
    source,
    created_at::timestamp as created_at,
    updated_at::timestamp as updated_at,
    status,
    {{ phone10('phone') }} as phone,
    nullif(lower(trim(email)), '') as email,
    {{ click_id('click_id') }} as click_id
from {{ source('bronze', 'crm_leads') }}
qualify row_number() over (partition by crm_id order by updated_at::timestamp desc, _batch_id desc) = 1
