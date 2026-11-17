-- Gold spend equals Silver spend, in total and per platform.
with s as (select platform, round(sum(spend), 2) as spend from {{ ref('slv_ad_spend') }} group by platform),

g as (select platform, round(sum(spend), 2) as spend from {{ ref('gold_campaign_cost') }} group by platform)

select s.platform, s.spend as silver_spend, g.spend as gold_spend
from s
full outer join g on s.platform = g.platform
where s.spend is distinct from g.spend
