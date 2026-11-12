-- The headline table: each channel's sell-through, on listings and on vehicles, over all 26 sales.
-- Listing basis counts every run; a car that no-sells twice and then sells is 1 of 3.
-- Vehicle basis counts each car once: did it sell in any run? It is always the higher of the two.
with listing_basis as (
    select
        channel,
        count(*) filter (where is_offered) as listings_offered,
        count(*) filter (where is_converted) as listings_converted,
        count(*) filter (where is_sold_on_block) as sold_on_block,
        count(*) filter (where is_if_sale) as if_sales,
        avg(bidders) filter (where is_offered) as avg_bidders,
        avg(price_to_book) as avg_price_to_book,
        sum(sold_price_usd) as gross_sales_usd
    from {{ ref('fct_listings') }}
    group by channel
),

vehicle_basis as (
    select
        channel,
        count(*) filter (where ever_offered) as vehicles_offered,
        count(*) filter (where ever_converted) as vehicles_sold
    from {{ ref('fct_vehicles') }}
    group by channel
)

select
    l.channel,
    l.listings_offered,
    l.sold_on_block,
    l.if_sales,
    l.listings_converted,
    l.sold_on_block / l.listings_offered as sell_through_on_block,
    l.listings_converted / l.listings_offered as conversion_rate,
    v.vehicles_offered,
    v.vehicles_sold,
    v.vehicles_sold / v.vehicles_offered as vehicle_sell_through,
    l.avg_bidders,
    l.avg_price_to_book,
    l.gross_sales_usd
from listing_basis as l
inner join vehicle_basis as v on l.channel = v.channel
