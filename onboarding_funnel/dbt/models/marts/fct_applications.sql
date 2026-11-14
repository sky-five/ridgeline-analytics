-- One row per person and program: every application id a person opened in a program is one application.
-- Each step is the first time the person reached it; the drop-off is the step after the last one reached.
with by_person as (
    select
        md5(applicant_key || '|' || program) as application_key,
        applicant_key,
        program,
        count(distinct application_id) as application_ids,
        min(event_at) filter (where event_type = 'application_started') as started_at,
        min(event_at) filter (where event_type = 'document_uploaded') as uploaded_at,
        min(event_at) filter (where event_type = 'application_submitted') as submitted_at,
        min(event_at) filter (
            where event_type in ('kyc_result', 'kyc_review_result') and detail = 'pass'
        ) as kyc_passed_at,
        min(event_at) filter (where event_type = 'account_funded') as funded_at,
        min(event_at) filter (where event_type = 'first_transaction') as first_transaction_at,
        arg_max(detail, event_at) filter (
            where event_type in ('kyc_result', 'kyc_review_result')
        ) as last_kyc_detail
    from {{ ref('stg_onboarding__events') }}
    group by applicant_key, program
),

flagged as (
    select
        *,
        cast(date_trunc('week', started_at) as date) as cohort_week,
        cast(date_trunc('week', started_at) as date) + 6 + {{ var('activation_days') }}
        <= cast('{{ var("as_of_date") }}' as date) as is_mature,
        date_diff('second', started_at, first_transaction_at) / 86400.0 as days_to_first_transaction,
        coalesce(
            first_transaction_at <= started_at + to_days({{ var('activation_days') }}), false
        ) as is_activated
    from by_person
)

select
    *,
    case
        when is_activated then null
        when funded_at is not null then 'first_transaction'
        when kyc_passed_at is not null then 'funding'
        when submitted_at is not null then 'kyc'
        when uploaded_at is not null then 'submit'
        else 'document_upload'
    end as drop_off_step,
    case
        when is_activated then null
        when first_transaction_at is not null then 'first_transaction_after_window'
        when funded_at is not null then 'no_first_transaction'
        when kyc_passed_at is not null then 'not_funded'
        when last_kyc_detail = 'review' then 'in_manual_review'
        when last_kyc_detail is not null then last_kyc_detail
        when submitted_at is not null then 'awaiting_kyc'
        when uploaded_at is not null then 'left_after_document_upload'
        else 'left_before_document_upload'
    end as drop_off_reason
from flagged
