-- The weekly table and the channel table count the same listings.
with weekly as (
    select channel, sum(offered) as offered, sum(sold_on_block) as sold, sum(if_sales) as if_sales
    from {{ ref('sell_through_weekly') }}
    group by channel
)

select c.channel
from {{ ref('sell_through_by_channel') }} as c
left join weekly as w on c.channel = w.channel
where w.offered is distinct from c.listings_offered
    or w.sold is distinct from c.sold_on_block
    or w.if_sales is distinct from c.if_sales
