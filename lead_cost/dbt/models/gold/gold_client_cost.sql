-- The same per client, with the leads no campaign can claim (organic, or a lost click id) counted beside it.
with paid as (
    select
        client,
        sum(spend) as spend,
        sum(leads)::int as paid_leads,
        sum(issued_leads)::int as issued_leads,
        sum(demos)::int as demos
    from {{ ref('gold_campaign_cost') }}
    group by client
),

unattributed as (
    select
        client,
        count(*)::int as unattributed_leads,
        (count(*) filter (where issued))::int as unattributed_issued
    from {{ ref('gold_leads') }}
    where campaign_id is null
    group by client
)

select
    p.client,
    round(p.spend, 2) as spend,
    p.paid_leads,
    p.issued_leads,
    p.demos,
    round(p.spend / nullif(p.issued_leads, 0), 2) as cost_per_issued_lead,
    round(p.spend / nullif(p.demos, 0), 2) as cost_per_demo,
    coalesce(u.unattributed_leads, 0) as unattributed_leads,
    coalesce(u.unattributed_issued, 0) as unattributed_issued
from paid as p
left join unattributed as u on p.client = u.client
