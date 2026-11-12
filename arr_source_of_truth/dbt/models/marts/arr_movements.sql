-- One row per customer and month in which the customer's month-end MRR changed, classified once.
with history as (
    select
        customer_id,
        month_start,
        mrr_cents,
        coalesce(lag(mrr_cents) over w, 0) as prev_cents,
        coalesce(max(mrr_cents) over (w rows between unbounded preceding and 1 preceding), 0) as ever_paid_cents
    from {{ ref('arr_customer_months') }}
    window w as (partition by customer_id order by month_start)
)

select
    customer_id,
    month_start,
    12 * prev_cents as opening_arr_cents,
    12 * mrr_cents as closing_arr_cents,
    12 * (mrr_cents - prev_cents) as change_arr_cents,
    case
        when prev_cents = 0 and ever_paid_cents = 0 then 'new'
        when prev_cents = 0 then 'reactivation'
        when mrr_cents = 0 then 'churn'
        when mrr_cents > prev_cents then 'expansion'
        else 'contraction'
    end as movement
from history
where mrr_cents <> prev_cents
