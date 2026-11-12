select
    bid_id,
    listing_id,
    bidder_id,
    bid_usd,
    is_online
from {{ source('raw_auction', 'bids') }}
