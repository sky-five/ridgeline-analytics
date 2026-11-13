select
    emp_id,
    pay_type,
    pay_date::date as pay_date,
    amount_cents::bigint as amount_cents
from {{ source('raw_payroll', 'pay_lines') }}
