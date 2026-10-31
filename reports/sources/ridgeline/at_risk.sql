select h.account_id, h.company_name, h.current_plan, h.mrr, h.health_score, h.risk_band,
       h.logins_30d, h.proposals_30d, h.tickets_90d, h.redo_90d, a.crew_size, a.region
from main.fct_account_health h
join main.dim_accounts a using (account_id)
where h.risk_band in ('at_risk', 'watch')
order by h.health_score, h.mrr desc
limit 50
