-- Cost per lead, per issued lead and per demo for every campaign. Spend counts only rows that map to a campaign;
-- assert_gold_spend_reconciles fails if any spend is left out that way.
with spend as (
    select
        campaign_id,
        sum(spend) as spend,
        sum(clicks)::bigint as clicks,
        sum(impressions)::bigint as impressions
    from {{ ref('slv_ad_spend') }}
    where campaign_id is not null
    group by campaign_id
),

leads as (
    select
        campaign_id,
        count(*) as leads,
        count(*) filter (where issued) as issued_leads,
        count(*) filter (where demo) as demos
    from {{ ref('gold_leads') }}
    where campaign_id is not null
    group by campaign_id
)

select
    c.campaign_id,
    c.client,
    c.platform,
    c.theme,
    coalesce(s.impressions, 0) as impressions,
    coalesce(s.clicks, 0) as clicks,
    round(coalesce(s.spend, 0), 2) as spend,
    coalesce(l.leads, 0) as leads,
    coalesce(l.issued_leads, 0) as issued_leads,
    coalesce(l.demos, 0) as demos,
    round(s.spend / nullif(l.leads, 0), 2) as cost_per_lead,
    round(s.spend / nullif(l.issued_leads, 0), 2) as cost_per_issued_lead,
    round(s.spend / nullif(l.demos, 0), 2) as cost_per_demo
from {{ ref('campaigns') }} as c
left join spend as s on c.campaign_id = s.campaign_id
left join leads as l on c.campaign_id = l.campaign_id
