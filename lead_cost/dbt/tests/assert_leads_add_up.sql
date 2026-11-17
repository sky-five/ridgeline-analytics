-- Every lead is counted once: paid plus unattributed equals gold_leads, per client, for leads and issued leads;
-- and demos <= issued leads <= leads on every campaign.
with l as (
    select client, count(*) as leads, count(*) filter (where issued) as issued
    from {{ ref('gold_leads') }}
    group by client
)

select l.client, 'client totals' as problem
from l
inner join {{ ref('gold_client_cost') }} as c on l.client = c.client
where
    c.paid_leads + c.unattributed_leads != l.leads
    or c.issued_leads + c.unattributed_issued != l.issued
union all
select campaign_id, 'funnel order' as problem
from {{ ref('gold_campaign_cost') }}
where demos > issued_leads or issued_leads > leads
