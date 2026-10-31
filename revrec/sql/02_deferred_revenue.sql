-- Deferred revenue rollforward for each closed month: opening + billings - recognized = closing.
-- Closing is computed independently (everything billed so far minus everything earned so far),
-- so the identity is a real check, not true by construction.

create or replace table fct_deferred_revenue as
with closed_months as (
    select month_start, month_end
    from month_spine
    where month_start <= (select as_of from params)
),

billed as (
    select
        cast(date_trunc('month', issued_on) as date) as month_start,
        sum(amount_cents) as billed_cents
    from invoice_lines
    group by 1
),

recognized as (
    select month_start, recognized_cents from fct_revenue_monthly
),

closing as (
    select
        m.month_start,
        (select coalesce(sum(amount_cents), 0) from invoice_lines where issued_on < m.month_end)
        - (select coalesce(sum(recognized_cents), 0) from rev_line_months where month_start < m.month_end)
            as closing_cents
    from closed_months as m
)

select
    m.month_start,
    coalesce(lag(c.closing_cents) over (order by m.month_start), 0) as opening_cents,
    coalesce(b.billed_cents, 0) as billed_cents,
    coalesce(r.recognized_cents, 0) as recognized_cents,
    c.closing_cents
from closed_months as m
inner join closing as c on m.month_start = c.month_start
left join billed as b on m.month_start = b.month_start
left join recognized as r on m.month_start = r.month_start
order by m.month_start;
