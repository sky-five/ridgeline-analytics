-- Bid activity per listing. Withdrawn listings have no bids and so no row here.
select
    listing_id,
    count(*) as bidders,
    count(*) filter (where is_online) as online_bidders,
    max(bid_usd) as high_bid_usd
from {{ ref('stg_auction__bids') }}
group by listing_id
