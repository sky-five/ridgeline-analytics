-- Three ARR definitions for every closed month, and a bridge that explains the gaps between them.
--
--   contract ARR   12 x month-end contract MRR at list price (what fct_arr_bridge reports)
--   billed ARR     what customers are committed to pay per year: monthly plans 12 x MRR,
--                  annual plans 10 x MRR (annual = 10 months up front)
--   run-rate ARR   12 x the month's recognized revenue (what the income statement supports)
--
-- Bridge: contract -> (annual prepay discount) -> billed -> (part-month new, part-month ended,
-- mid-month price changes, calendar and rounding) -> run-rate. Each item is summed per subscription,
-- and the totals are tied back to fct_arr_bridge and fct_revenue_monthly in the tests, so the bridge
-- is checked against numbers built a different way, not true by construction.

create or replace table sub_billing_interval as
select subscription_id, max(datediff('month', period_start, period_end)) as months_per_period
from invoice_lines
where kind = 'subscription'
group by subscription_id;

create or replace table arr_sub_months as
with months as (
    select month_start, month_end, cast(month_end - interval 1 day as date) as month_last_day
    from month_spine
    where month_end <= (select as_of from params) + interval 1 day
),

grid as (
    select s.subscription_id, m.month_start, m.month_end, m.month_last_day
    from (select distinct subscription_id from subscription_changes) as s
    cross join months as m
),

month_end_mrr as (
    select g.subscription_id, g.month_start, coalesce(c.mrr_cents, 0) as mrr_cents
    from grid as g
    asof left join subscription_changes as c
        on g.subscription_id = c.subscription_id and g.month_last_day >= c.effective_on
),

revenue as (
    select subscription_id, month_start, sum(recognized_cents) as recognized_cents
    from rev_line_months
    group by subscription_id, month_start
),

-- Changes on the 1st apply to the whole month, so only changes after the 1st make a part month.
mid_month as (
    select
        g.subscription_id,
        g.month_start,
        bool_or(c.reason = 'new') as started,
        bool_or(c.mrr_cents = 0) as ended
    from grid as g
    inner join subscription_changes as c
        on g.subscription_id = c.subscription_id
        and c.effective_on > g.month_start
        and c.effective_on < g.month_end
    group by g.subscription_id, g.month_start
),

joined as (
    select
        g.subscription_id,
        g.month_start,
        e.mrr_cents,
        coalesce(i.months_per_period, 1) = 12 as is_annual,
        coalesce(r.recognized_cents, 0) as recognized_cents,
        case
            when mm.started then 'new_part_month'
            when mm.ended then 'ended_part_month'
            when mm.subscription_id is not null then 'price_change_part_month'
            else 'calendar_and_rounding'
        end as bridge_item
    from grid as g
    inner join month_end_mrr as e on g.subscription_id = e.subscription_id and g.month_start = e.month_start
    left join sub_billing_interval as i on g.subscription_id = i.subscription_id
    left join revenue as r on g.subscription_id = r.subscription_id and g.month_start = r.month_start
    left join mid_month as mm on g.subscription_id = mm.subscription_id and g.month_start = mm.month_start
)

select
    subscription_id,
    month_start,
    is_annual,
    bridge_item,
    12 * mrr_cents as contract_arr_cents,
    (case when is_annual then 10 else 12 end) * mrr_cents as billed_arr_cents,
    12 * recognized_cents as run_rate_arr_cents
from joined
where mrr_cents <> 0 or recognized_cents <> 0;

create or replace table fct_arr_definitions as
select
    m.month_start,
    coalesce(sum(s.contract_arr_cents), 0) as contract_arr_cents,
    coalesce(sum(s.billed_arr_cents - s.contract_arr_cents), 0) as annual_discount_cents,
    coalesce(sum(s.billed_arr_cents), 0) as billed_arr_cents,
    coalesce(sum(s.run_rate_arr_cents - s.billed_arr_cents)
        filter (where s.bridge_item = 'new_part_month'), 0) as new_part_month_cents,
    coalesce(sum(s.run_rate_arr_cents - s.billed_arr_cents)
        filter (where s.bridge_item = 'ended_part_month'), 0) as ended_part_month_cents,
    coalesce(sum(s.run_rate_arr_cents - s.billed_arr_cents)
        filter (where s.bridge_item = 'price_change_part_month'), 0) as price_change_part_month_cents,
    coalesce(sum(s.run_rate_arr_cents - s.billed_arr_cents)
        filter (where s.bridge_item = 'calendar_and_rounding'), 0) as calendar_and_rounding_cents,
    coalesce(sum(s.run_rate_arr_cents), 0) as run_rate_arr_cents
from month_spine as m
left join arr_sub_months as s on m.month_start = s.month_start
where m.month_end <= (select as_of from params) + interval 1 day
group by m.month_start
order by m.month_start;
