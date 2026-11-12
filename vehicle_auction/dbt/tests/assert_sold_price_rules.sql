-- A sale on the block meets the reserve; an if-sale is under it; a sold price is always the high bid.
select listing_id
from {{ ref('fct_listings') }}
where (is_sold_on_block and sold_price_usd < reserve_usd)
    or (is_if_sale and sold_price_usd >= reserve_usd)
    or (is_converted and sold_price_usd <> high_bid_usd)
    or (not is_converted and sold_price_usd is not null)
