-- The price is MSRP less the dealer discount and the customer cash; financing support is not in it.
select sale_id
from {{ ref('fct_sales') }}
where abs(transaction_price - (msrp - dealer_discount - customer_cash_amount)) >= 0.01
