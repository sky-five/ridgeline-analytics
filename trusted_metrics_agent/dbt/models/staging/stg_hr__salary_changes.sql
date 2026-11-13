select
    emp_id,
    effective_date::date as effective_date,
    annual_base_cents::bigint as annual_base_cents
from {{ source('raw_hr', 'salary_changes') }}
