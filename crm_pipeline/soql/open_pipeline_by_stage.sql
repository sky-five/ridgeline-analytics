select stage, count(*) as deals, sum(amount_usd) as pipeline
from stg_crm__opportunities
where not is_closed
group by stage
order by pipeline desc
