-- Every spend row and every click names a known campaign (a renamed campaign would drop out of the cost figures).
select 'spend' as feed, platform, campaign_name_raw as name, count(*) as n_rows
from {{ ref('slv_ad_spend') }}
where campaign_id is null
group by all
union all
select 'clicks' as feed, platform, campaign_key as name, count(*) as n_rows
from {{ ref('slv_ad_clicks') }}
where campaign_id is null
group by all
