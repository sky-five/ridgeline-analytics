-- Each offered car lands in exactly one first-offered week, so the weeks add up to the channel table.
with weekly as (
    select channel, sum(vehicles_offered) as offered, sum(vehicles_sold) as sold
    from {{ ref('vehicle_sell_through_weekly') }}
    group by channel
)

select c.channel
from {{ ref('sell_through_by_channel') }} as c
left join weekly as w on c.channel = w.channel
where w.offered is distinct from c.vehicles_offered
    or w.sold is distinct from c.vehicles_sold
