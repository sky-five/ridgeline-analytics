-- On-block sell-through <= conversion (adds if-sales) <= vehicle sell-through (counts each car once).
select channel
from {{ ref('sell_through_by_channel') }}
where not (0 <= sell_through_on_block and sell_through_on_block <= conversion_rate
    and conversion_rate <= vehicle_sell_through and vehicle_sell_through <= 1)
