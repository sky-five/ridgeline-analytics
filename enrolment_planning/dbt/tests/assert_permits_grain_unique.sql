select permit_month, region_code, study_level, count(*) as n
from {{ ref('fct_study_permits_month') }}
group by all
having count(*) > 1
