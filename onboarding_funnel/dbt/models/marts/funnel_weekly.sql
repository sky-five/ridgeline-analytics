-- Program x cohort week (the week a person first started). Activation counted two ways: per application id
-- (what a dashboard counting ids shows) and per person (fct_applications). KYC pass rate is per person submitted.
with ids as (
    select
        program,
        cast(date_trunc('week', started_at) as date) as cohort_week,
        count(*) as application_ids,
        count(*) filter (
            where first_transaction_at <= started_at + to_days({{ var('activation_days') }})
        ) as activated_application_ids
    from {{ ref('fct_application_ids') }}
    group by all
),

people as (
    select
        program,
        cohort_week,
        bool_and(is_mature) as is_mature,
        count(*) as applicants,
        count(*) filter (where submitted_at is not null) as submitted,
        count(*) filter (where kyc_passed_at is not null) as kyc_passed,
        count(*) filter (where is_activated) as activated
    from {{ ref('fct_applications') }}
    group by all
)

select
    people.program,
    people.cohort_week,
    people.is_mature,
    ids.application_ids,
    people.applicants,
    ids.application_ids / people.applicants as application_ids_per_applicant,
    ids.activated_application_ids,
    people.activated,
    ids.activated_application_ids / ids.application_ids as activation_rate_per_id,
    people.activated / people.applicants as activation_rate,
    people.submitted,
    people.kyc_passed,
    people.kyc_passed / nullif(people.submitted, 0) as kyc_pass_rate
from people
inner join ids on people.program = ids.program and people.cohort_week = ids.cohort_week
order by people.program, people.cohort_week
