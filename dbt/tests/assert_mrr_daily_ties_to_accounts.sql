-- The last day's company MRR must equal the sum of every account's current MRR.
with last_day as (
    select mrr from {{ ref('fct_mrr_daily') }}
    where date_day = {{ as_of_date() }}
),

accounts as (
    select sum(current_mrr) as mrr from {{ ref('dim_accounts') }}
)

select l.mrr as daily_mrr, a.mrr as account_mrr
from last_day as l
cross join accounts as a
where abs(l.mrr - a.mrr) > 0.01
