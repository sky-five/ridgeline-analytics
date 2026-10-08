with source as (
    select * from {{ source('support', 'support_tickets') }}
)

select
    ticket_id,
    account_id,
    {{ to_utc('created_at') }} as created_at,
    {{ to_utc('first_reply_at') }} as first_reply_at,
    {{ to_utc('solved_at') }} as solved_at,
    status,
    priority,
    channel,
    subject,
    body,
    {{ to_utc('updated_at') }} as updated_at
from source
