select cancel_reason, count(*) as churned_accounts
from main.dim_accounts
where churned_at >= (select max(churned_at) from main.dim_accounts) - interval 12 month
group by 1
order by 2 desc
