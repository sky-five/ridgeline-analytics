select
    claim_id,
    policy_id,
    peril_id,
    status,
    cast(loss_date as date) as loss_date,
    cast(reported_date as date) as reported_date,
    cast(closed_date as date) as closed_date,
    cast(incurred_amount as decimal(14, 2)) as incurred_amount,
    cast(paid_amount as decimal(14, 2)) as paid_amount
from {{ source('raw_claims', 'claims') }}
