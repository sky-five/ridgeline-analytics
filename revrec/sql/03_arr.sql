-- ARR comes from the contract side (subscription MRR as of each month end), not from invoices.
-- Movements are classified per customer, so moving from one subscription to another is not churn + new.

create or replace table customer_month_mrr as
with month_ends as (
    select month_start, cast(month_end - interval 1 day as date) as month_last_day
    from month_spine
    where month_start <= (select as_of from params)
),

sub_months as (
    select s.subscription_id, s.customer_id, m.month_start, m.month_last_day
    from (select distinct subscription_id, customer_id from subscription_changes) as s
    cross join month_ends as m
),

sub_mrr as (
    select sm.customer_id, sm.month_start, coalesce(c.mrr_cents, 0) as mrr_cents
    from sub_months as sm
    asof left join subscription_changes as c
        on sm.subscription_id = c.subscription_id and sm.month_last_day >= c.effective_on
)

select customer_id, month_start, sum(mrr_cents) as mrr_cents
from sub_mrr
group by customer_id, month_start;

create or replace table fct_arr_movements as
with history as (
    select
        customer_id,
        month_start,
        mrr_cents,
        coalesce(lag(mrr_cents) over w, 0) as prev_cents,
        coalesce(max(mrr_cents) over (w rows between unbounded preceding and 1 preceding), 0) as ever_paid_cents
    from customer_month_mrr
    window w as (partition by customer_id order by month_start)
)

select
    customer_id,
    month_start,
    prev_cents as opening_mrr_cents,
    mrr_cents as closing_mrr_cents,
    mrr_cents - prev_cents as change_mrr_cents,
    case
        when prev_cents = 0 and ever_paid_cents = 0 then 'new'
        when prev_cents = 0 then 'reactivation'
        when mrr_cents = 0 then 'churn'
        when mrr_cents > prev_cents then 'expansion'
        else 'contraction'
    end as movement
from history
where mrr_cents <> prev_cents;

create or replace table fct_arr_bridge as
with totals as (
    select month_start, 12 * sum(mrr_cents) as closing_arr_cents, count(*) filter (where mrr_cents > 0) as customers
    from customer_month_mrr
    group by month_start
),

moves as (
    select
        month_start,
        12 * sum(change_mrr_cents) filter (where movement = 'new') as new_cents,
        12 * sum(change_mrr_cents) filter (where movement = 'reactivation') as reactivation_cents,
        12 * sum(change_mrr_cents) filter (where movement = 'expansion') as expansion_cents,
        12 * sum(change_mrr_cents) filter (where movement = 'contraction') as contraction_cents,
        12 * sum(change_mrr_cents) filter (where movement = 'churn') as churn_cents
    from fct_arr_movements
    group by month_start
)

select
    t.month_start,
    coalesce(lag(t.closing_arr_cents) over (order by t.month_start), 0) as opening_arr_cents,
    coalesce(m.new_cents, 0) as new_cents,
    coalesce(m.reactivation_cents, 0) as reactivation_cents,
    coalesce(m.expansion_cents, 0) as expansion_cents,
    coalesce(m.contraction_cents, 0) as contraction_cents,
    coalesce(m.churn_cents, 0) as churn_cents,
    t.closing_arr_cents,
    t.customers
from totals as t
left join moves as m on t.month_start = m.month_start
order by t.month_start;
