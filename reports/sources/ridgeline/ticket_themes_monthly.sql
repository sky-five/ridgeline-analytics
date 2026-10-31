select date_trunc('month', created_at) as month, churn_theme, count(*) as tickets
from main.fct_support_tickets
where is_paying_at_creation and created_at >= '2025-01-01'
group by 1, 2
order by 1
