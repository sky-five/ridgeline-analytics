-- Opening + movements = closing, and each month opens where the last one closed.
select month_start
from (
    select *, lag(closing_arr_cents) over (order by month_start) as prev_closing
    from {{ ref('arr_bridge') }}
)
where opening_arr_cents + new_arr_cents + reactivation_arr_cents + expansion_arr_cents
    + contraction_arr_cents + churn_arr_cents <> closing_arr_cents
    or opening_arr_cents <> coalesce(prev_closing, 0)
