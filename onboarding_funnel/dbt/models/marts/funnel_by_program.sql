-- The funnel per program on mature cohorts (every person has had the full activation window): people
-- reaching each step, and each step's rate from the one before.
with steps as (
    select
        program,
        count(*) as started,
        count(uploaded_at) as uploaded,
        count(submitted_at) as submitted,
        count(kyc_passed_at) as kyc_passed,
        count(funded_at) as funded,
        count(*) filter (where is_activated) as activated
    from {{ ref('fct_applications') }}
    where is_mature
    group by program
)

select
    *,
    uploaded / started as upload_rate,
    submitted / uploaded as submit_rate,
    kyc_passed / submitted as kyc_pass_rate,
    funded / kyc_passed as funding_rate,
    activated / funded as first_transaction_rate,
    activated / started as activation_rate
from steps
order by program
