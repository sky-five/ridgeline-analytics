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
