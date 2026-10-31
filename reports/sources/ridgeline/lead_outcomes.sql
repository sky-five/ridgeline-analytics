select outcome_group, count(*) as leads
from main.fct_contractor_leads
group by 1
