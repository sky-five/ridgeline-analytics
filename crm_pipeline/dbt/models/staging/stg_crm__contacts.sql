select
    contact_id,
    account_id,
    lower(email) as email,
    title,
    created_at
from {{ source('raw_crm', 'contacts') }}
