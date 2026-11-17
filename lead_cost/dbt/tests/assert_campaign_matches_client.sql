-- A lead's campaign belongs to the lead's client (a click id or tracking number joined to the wrong client fails).
select l.lead_key, l.client, c.client as campaign_client
from {{ ref('gold_leads') }} as l
inner join {{ ref('campaigns') }} as c on l.campaign_id = c.campaign_id
where l.client != c.client
