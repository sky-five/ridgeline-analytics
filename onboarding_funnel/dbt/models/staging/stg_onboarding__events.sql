-- One row per event: a redelivered event keeps its first delivery. applicant_key identifies a person
-- within the platform from the email (trimmed, lower case) and date of birth, not from the application id.
with ranked as (
    select
        *,
        row_number() over (partition by event_id order by received_at) as delivery
    from {{ source('raw_onboarding', 'events') }}
)

select
    event_id,
    application_id,
    program,
    event_type,
    detail,
    cast(event_at as timestamp) as event_at,
    cast(received_at as timestamp) as received_at,
    lower(trim(email)) as email_normalised,
    cast(date_of_birth as date) as date_of_birth,
    md5(lower(trim(email)) || '|' || cast(date_of_birth as varchar)) as applicant_key
from ranked
where delivery = 1
