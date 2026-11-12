select
    deal_id,
    customer_id,
    deal_type,
    cast(close_date as date) as close_date,
    cast(date_trunc('month', close_date) as date) as month_start,
    booked_arr_cents
from {{ source('raw_crm', 'won_deals') }}
