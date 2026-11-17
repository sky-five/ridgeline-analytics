-- Generated from staging_codegen/sources/app_db.yml by python -m staging_codegen. Do not edit.
with source as (
    select * from {{ source('app_db', 'accounts') }}
)

select
    account_id,
    company_name,
    {{ to_utc('signup_at') }} as signup_at,
    channel,
    campaign_id,
    region,
    crew_size,
    {{ to_utc('updated_at') }} as updated_at
from source
