-- cohort-size weighted average across every cohort old enough to reach each month
select months_since_start,
       sum(retained_accounts) / sum(cohort_accounts) as logo_retention,
       sum(retained_mrr) / nullif(sum(cohort_start_mrr), 0) as nrr,
       count(*) as cohorts
from main.fct_cohort_retention
where months_since_start between 0 and 24
group by 1
order by 1
