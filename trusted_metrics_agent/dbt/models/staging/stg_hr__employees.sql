select
    e.emp_id,
    e.department,
    e.location,
    e.employment_type,
    e.job_level::integer as job_level,
    e.hire_date::date as hire_date,
    t.term_date::date as term_date,
    t.term_reason
from {{ source('raw_hr', 'employees') }} as e
left join {{ source('raw_hr', 'terminations') }} as t on e.emp_id = t.emp_id
