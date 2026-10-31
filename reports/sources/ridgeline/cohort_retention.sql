select cohort_month, months_since_start, cohort_accounts, logo_retention, nrr, grr
from main.fct_cohort_retention
where months_since_start between 0 and 18
