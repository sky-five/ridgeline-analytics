-- One row per click id the ad platforms reported, with its campaign.
with clicks as (
    select 'search' as platform, click_id, clicked_at, campaign_name, _batch_id
    from {{ source('bronze', 'search_clicks') }}
    union all
    select 'social' as platform, click_id, clicked_at, campaign_name, _batch_id
    from {{ source('bronze', 'social_clicks') }}
)

select
    k.platform,
    trim(k.click_id) as click_id,
    k.clicked_at::timestamp as clicked_at,
    {{ campaign_key('k.campaign_name') }} as campaign_key,
    c.campaign_id,
    c.client
from clicks as k
left join {{ ref('campaigns') }} as c
    on k.platform = c.platform and {{ campaign_key('k.campaign_name') }} = c.campaign_key
qualify row_number() over (partition by trim(k.click_id) order by k._batch_id) = 1
