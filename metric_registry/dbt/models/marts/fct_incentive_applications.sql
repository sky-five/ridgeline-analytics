-- One row per incentive program applied to a sale. Carries the sale's date, dealer and vehicle so program
-- spend can be cut by the same dimensions as sales without a second join hop.
select
    i.application_id,
    i.sale_id,
    i.program_id,
    s.sale_date,
    s.dealer_id,
    s.vehicle_id,
    s.finance_type,
    i.amount
from {{ ref('stg_vehicles__incentives') }} as i
join {{ ref('stg_vehicles__sales') }} as s using (sale_id)
