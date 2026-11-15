select fall_year, region_code, isced_code, institution_code, program_code, status_code, count(*) as n
from {{ ref('fct_enrolment') }}
group by all
having count(*) > 1
