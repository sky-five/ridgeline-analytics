-- One row per consigned vehicle: how its first run went and whether it sold in any run.
with runs as (
    select
        vehicle_id,
        count(*) as runs,
        count(*) filter (where is_offered) as runs_offered,
        bool_or(is_converted) as ever_converted,
        max(sold_price_usd) as sold_price_usd,
        max(case when run_number = 1 then status end) as first_run_status,
        max(case when run_number = 1 then sold_price_usd end) as first_run_price_usd
    from {{ ref('fct_listings') }}
    group by vehicle_id
)

select
    v.vehicle_id,
    v.seller_id,
    v.channel,
    v.segment,
    v.book_value_usd,
    v.consigned_on,
    t.arm as test_arm,
    r.runs,
    r.runs_offered,
    r.first_run_status,
    r.first_run_status <> 'withdrawn' as first_run_offered,
    r.first_run_status in ('sold', 'if_sale') as first_run_converted,
    coalesce(r.first_run_price_usd, 0) as first_run_proceeds_usd,
    r.runs_offered > 0 as ever_offered,
    r.ever_converted,
    r.sold_price_usd
from {{ ref('stg_auction__vehicles') }} as v
inner join runs as r on v.vehicle_id = r.vehicle_id
left join {{ ref('stg_auction__test_assignments') }} as t on v.vehicle_id = t.vehicle_id
