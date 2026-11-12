-- Listing-basis sell-through by channel and sale week. Denominator: listings offered (withdrawn excluded).
select
    channel,
    sale_week,
    count(*) as listings,
    count(*) filter (where not is_offered) as withdrawn,
    count(*) filter (where is_offered) as offered,
    count(*) filter (where is_sold_on_block) as sold_on_block,
    count(*) filter (where is_if_sale) as if_sales,
    count(*) filter (where is_offered and not is_converted) as no_sales,
    count(*) filter (where is_sold_on_block) / count(*) filter (where is_offered) as sell_through_on_block,
    count(*) filter (where is_converted) / count(*) filter (where is_offered) as conversion_rate,
    avg(bidders) filter (where is_offered) as avg_bidders,
    sum(sold_price_usd) as gross_sales_usd
from {{ ref('fct_listings') }}
group by channel, sale_week
