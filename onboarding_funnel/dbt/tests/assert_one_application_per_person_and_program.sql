-- A person who opened several application ids in a program is still one application.
select applicant_key, program
from {{ ref('fct_applications') }}
group by applicant_key, program
having count(*) > 1
