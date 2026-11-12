-- One row per run of a vehicle through a sale, with the flags every sell-through metric is built from.
-- offered: the vehicle ran (withdrawn before the sale does not count).
-- sold_on_block: the high bid met the reserve. if_sale: the seller accepted a high bid under the reserve afterwards.
-- converted: either of the two.
select
    l.listing_id,
    l.vehicle_id,
    l.sale_date,
    date_trunc('week', l.sale_date) as sale_week,
    l.run_number,
    l.channel,
    v.segment,
    v.seller_id,
    v.book_value_usd,
    l.reserve_usd,
    l.reserve_usd / v.book_value_usd as reserve_to_book,
    l.status,
    l.status <> 'withdrawn' as is_offered,
    l.status = 'sold' as is_sold_on_block,
    l.status = 'if_sale' as is_if_sale,
    l.status in ('sold', 'if_sale') as is_converted,
    coalesce(b.bidders, 0) as bidders,
    coalesce(b.online_bidders, 0) as online_bidders,
    b.high_bid_usd,
    l.sold_price_usd,
    l.sold_price_usd / v.book_value_usd as price_to_book,
    t.arm as test_arm
from {{ ref('stg_auction__listings') }} as l
inner join {{ ref('stg_auction__vehicles') }} as v on l.vehicle_id = v.vehicle_id
left join {{ ref('int_listing_bids') }} as b on l.listing_id = b.listing_id
left join {{ ref('stg_auction__test_assignments') }} as t on l.vehicle_id = t.vehicle_id
