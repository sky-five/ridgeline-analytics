select
    lead_id,
    company,
    lead_source,
    status,
    owner_id,
    created_at,
    working_at,
    converted_at,
    disqualified_at,
    disqualify_reason,
    converted_account_id,
    converted_opportunity_id
from {{ source('raw_crm', 'leads') }}
