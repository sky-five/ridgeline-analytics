-- One row per change to a subscription's MRR, with the change in MRR it made.
select
    subscription_id || '@' || cast(effective_on as varchar) as change_key,
    subscription_id,
    customer_id,
    cast(effective_on as date) as effective_on,
    cast(date_trunc('month', effective_on) as date) as month_start,
    reason,
    reason in ('new', 'upgrade') as is_sales_led,
    mrr_cents,
    mrr_cents - coalesce(lag(mrr_cents) over (partition by subscription_id order by effective_on), 0)
        as delta_mrr_cents
from {{ source('raw_billing', 'subscription_changes') }}
