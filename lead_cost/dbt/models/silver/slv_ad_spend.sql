-- One row per platform, campaign and day. Search restates the last three days in every file and one social file
-- arrived twice, so the latest delivered row for a day wins. campaign_id is null when the name maps to no campaign.
with search as (
    select
        'search' as platform,
        "date"::date as day,
        {{ campaign_key('campaign_name') }} as campaign_key,
        campaign_name as campaign_name_raw,
        impressions::int as impressions,
        clicks::int as clicks,
        cost_micros::bigint / 1000000.0 as spend,
        _batch_id
    from {{ source('bronze', 'search_spend') }}
),

social as (
    select
        'social' as platform,
        strptime(date_start, '%m/%d/%Y')::date as day,
        {{ campaign_key('campaign') }} as campaign_key,
        campaign as campaign_name_raw,
        impressions::int as impressions,
        link_clicks::int as clicks,
        amount_spent::decimal(12, 2)::double as spend,
        _batch_id
    from {{ source('bronze', 'social_spend') }}
),

latest as (
    select *
    from (select * from search union all select * from social)
    qualify row_number() over (partition by platform, day, campaign_key order by _batch_id desc) = 1
)

select
    l.platform,
    l.day,
    l.campaign_key,
    l.campaign_name_raw,
    c.campaign_id,
    c.client,
    l.impressions,
    l.clicks,
    round(l.spend, 2)::decimal(14, 2) as spend,  -- exact, so sums don't depend on thread order
    l._batch_id as batch_id
from latest as l
left join {{ ref('campaigns') }} as c
    on l.platform = c.platform and l.campaign_key = c.campaign_key
