select risk_band, count(*) as accounts, sum(mrr) as mrr
from main.fct_account_health
group by 1
