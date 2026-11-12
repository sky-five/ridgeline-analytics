-- Contract MRR per customer at each month end: the latest change on each subscription by that day.
with sub_months as (
    select s.subscription_id, s.customer_id, m.month_start, m.month_last_day
    from (select distinct subscription_id, customer_id from {{ ref('stg_billing__subscription_changes') }}) as s
    cross join {{ ref('arr_months') }} as m
),

sub_mrr as (
    select sm.customer_id, sm.month_start, coalesce(c.mrr_cents, 0) as mrr_cents
    from sub_months as sm
    asof left join {{ ref('stg_billing__subscription_changes') }} as c
        on sm.subscription_id = c.subscription_id and sm.month_last_day >= c.effective_on
)

select customer_id, month_start, sum(mrr_cents) as mrr_cents
from sub_mrr
group by customer_id, month_start
