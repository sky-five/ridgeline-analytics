select
    claim_id,
    policy_id,
    term_id,
    loss_date::date as loss_date,
    reported_date::date as reported_date,
    amount::decimal(18, 2) as incurred,
    cause
from {{ source('raw_book', 'claims') }}
