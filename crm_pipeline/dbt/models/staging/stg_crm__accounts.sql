-- One row per account record as typed into the CRM, duplicates included.
select
    account_id,
    trim(name) as account_name,
    -- the key the dedupe matches on: case, '&' vs 'and', punctuation and a trailing company suffix ignored
    regexp_replace(
        trim(regexp_replace(replace(lower(name), '&', 'and'), '[.,]', '', 'g')),
        '\s+(llc|inc|co|corp|ltd)$', ''
    ) as name_key,
    nullif(trim(lower(website)), '') as website,
    billing_state,
    employee_count,
    segment,
    owner_id,
    source_lead_id,
    created_at
from {{ source('raw_crm', 'accounts') }}
