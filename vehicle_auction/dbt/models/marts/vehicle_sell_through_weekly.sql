-- Vehicle-basis sell-through by channel and the week each car was first offered.
-- A car counts once, in the week of its first offered run, as sold if it sold in any run.
-- Cars first offered in the last weeks have had fewer chances to relist, so this rate dips at the end.
with first_offered as (
    select vehicle_id, min(sale_week) as first_offered_week
    from {{ ref('fct_listings') }}
    where is_offered
    group by vehicle_id
)

select
    v.channel,
    f.first_offered_week as sale_week,
    count(*) as vehicles_offered,
    count(*) filter (where v.ever_converted) as vehicles_sold,
    count(*) filter (where v.ever_converted) / count(*) as vehicle_sell_through
from {{ ref('fct_vehicles') }} as v
inner join first_offered as f on v.vehicle_id = f.vehicle_id
group by v.channel, f.first_offered_week
