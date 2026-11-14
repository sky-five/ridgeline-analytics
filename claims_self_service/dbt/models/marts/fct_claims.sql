-- One row per reported claim.
-- is_decided: approved or denied (a withdrawn claim is closed but never decided).
-- cycle_days: reported to closed, for closed claims only.
-- incurred_amount: paid for a closed claim; the case reserve for an open one.
select
    claim_id,
    policy_id,
    peril_id,
    status,
    loss_date,
    reported_date,
    closed_date,
    status <> 'open' as is_closed,
    status = 'approved' as is_approved,
    status in ('approved', 'denied') as is_decided,
    case when status <> 'open' then datediff('day', reported_date, closed_date) end as cycle_days,
    datediff('day', loss_date, reported_date) as report_lag_days,
    incurred_amount,
    paid_amount
from {{ ref('stg_claims__claims') }}
