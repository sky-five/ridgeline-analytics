select
    sale_id,
    cast(sale_date as date) as sale_date,
    dealer_id,
    vehicle_id,
    finance_type,
    is_returning_customer,
    cast(msrp as decimal(12, 2)) as msrp,
    cast(dealer_discount as decimal(12, 2)) as dealer_discount,
    cast(transaction_price as decimal(12, 2)) as transaction_price
from {{ source('raw_vehicles', 'sales') }}
