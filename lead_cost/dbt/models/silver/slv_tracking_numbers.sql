-- Call tracking's numbers: each campaign has its own; a client's main line has none.
select
    {{ phone10('t.tracking_number') }} as tracking_phone,
    lower(t.platform) as platform,
    {{ campaign_key('t.campaign_label') }} as campaign_key,
    c.campaign_id,
    c.client
from {{ source('bronze', 'tracking_numbers') }} as t
left join {{ ref('campaigns') }} as c
    on lower(t.platform) = c.platform and {{ campaign_key('t.campaign_label') }} = c.campaign_key
