-- One row per application id, the way a dashboard counting application ids sees the funnel. Kept to show
-- what that count gets wrong; the funnel metrics use fct_applications.
select
    application_id,
    program,
    any_value(applicant_key) as applicant_key,
    min(event_at) filter (where event_type = 'application_started') as started_at,
    min(event_at) filter (where event_type = 'first_transaction') as first_transaction_at
from {{ ref('stg_onboarding__events') }}
group by application_id, program
