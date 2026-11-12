-- Every listing is exactly one of withdrawn, sold on the block, if-sale or no-sale.
select listing_id
from {{ ref('fct_listings') }}
where (not is_offered)::int + is_sold_on_block::int + is_if_sale::int
    + (is_offered and not is_converted)::int <> 1
