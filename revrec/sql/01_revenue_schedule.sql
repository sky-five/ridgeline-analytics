-- Ratable revenue: each invoice line is earned evenly by day over its service period.
-- Policy: revenue earned through a date = amount * days elapsed / days in period, truncated to the cent.
-- A month's revenue is the difference between two such cumulative figures, so the months of a line
-- always add back to its amount exactly, with no rounding drift.

create or replace table month_spine as
select cast(m as date) as month_start, cast(m + interval 1 month as date) as month_end
from (
    select unnest(generate_series(
        cast(date_trunc('month', min(d)) as timestamp),
        cast(date_trunc('month', max(d)) as timestamp),
        interval 1 month
    )) as m
    from (
        select period_start as d from invoice_lines
        union all select period_end from invoice_lines
        union all select effective_on from subscription_changes
        union all select as_of from params
    )
);

create or replace table rev_line_months as
with lines as (
    select
        *,
        datediff('day', period_start, period_end) as total_days
    from invoice_lines
),

overlap as (
    select
        l.line_id,
        l.customer_id,
        l.subscription_id,
        l.kind,
        l.amount_cents,
        l.total_days,
        m.month_start,
        least(greatest(datediff('day', l.period_start, m.month_start), 0), l.total_days) as days_before,
        least(greatest(datediff('day', l.period_start, m.month_end), 0), l.total_days) as days_through
    from lines as l
    inner join month_spine as m
        on m.month_start < l.period_end and m.month_end > l.period_start
)

select
    *,
    sign(amount_cents) * (abs(amount_cents) * days_through // total_days)
    - sign(amount_cents) * (abs(amount_cents) * days_before // total_days) as recognized_cents
from overlap;

create or replace table fct_revenue_monthly as
select
    month_start,
    sum(recognized_cents) as recognized_cents,
    sum(recognized_cents) filter (where kind = 'subscription') as subscription_cents,
    sum(recognized_cents) filter (where kind = 'proration') as proration_cents,
    sum(recognized_cents) filter (where kind = 'credit') as credit_cents,
    month_start > (select as_of from params) as is_future
from rev_line_months
group by month_start
order by month_start;
