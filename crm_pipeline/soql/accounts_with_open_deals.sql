-- The parent-to-child subquery becomes a join: one row per open deal, account fields repeated.
select a.account_name, a.billing_state, o.opportunity_id, o.stage, o.amount_usd
from stg_crm__accounts as a
inner join stg_crm__opportunities as o on a.account_id = o.account_id
where a.billing_state = 'TX' and not o.is_closed
order by a.account_name, o.amount_usd desc
