-- One row per vehicle sold, with the incentives applied to it rolled up.
with incentives as (
    select
        i.sale_id,
        sum(i.amount) as incentive_amount,
        sum(case when p.is_customer_cash then i.amount else 0 end) as customer_cash_amount,
        count(*) as programs_applied
    from {{ ref('stg_vehicles__incentives') }} as i
    join {{ ref('stg_vehicles__programs') }} as p using (program_id)
    group by i.sale_id
)

select
    s.sale_id,
    s.sale_date,
    s.dealer_id,
    s.vehicle_id,
    s.finance_type,
    s.is_returning_customer,
    -- the last ten days of the calendar quarter, when the quarter-end cash program runs
    s.sale_date > cast(date_trunc('quarter', s.sale_date) + interval 3 month - interval 11 day as date) as is_quarter_end,
    s.msrp,
    s.dealer_discount,
    s.transaction_price,
    coalesce(i.incentive_amount, 0) as incentive_amount,
    coalesce(i.customer_cash_amount, 0) as customer_cash_amount,
    coalesce(i.programs_applied, 0) as programs_applied,
    coalesce(i.programs_applied, 0) > 0 as has_incentive
from {{ ref('stg_vehicles__sales') }} as s
left join incentives as i using (sale_id)
