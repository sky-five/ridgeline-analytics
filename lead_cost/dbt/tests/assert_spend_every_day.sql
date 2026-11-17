-- Every campaign has spend reported for every day from first_day to as_of (a missing export day fails here).
with days as (
    select d::date as day
    from range(date '{{ var("first_day") }}', date '{{ var("as_of") }}' + interval 1 day, interval 1 day) as t (d)
)

select c.campaign_id, d.day
from {{ ref('campaigns') }} as c
cross join days as d
left join {{ ref('slv_ad_spend') }} as s on c.campaign_id = s.campaign_id and d.day = s.day
where s.campaign_id is null
