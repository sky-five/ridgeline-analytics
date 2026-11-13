-- Nobody is paid for a month that ended before they were hired or started after they left.
select p.emp_id, p.pay_date
from {{ ref('stg_payroll__pay_lines') }} as p
inner join {{ ref('stg_hr__employees') }} as e on p.emp_id = e.emp_id
where
    p.pay_date < e.hire_date
    or (e.term_date is not null and date_trunc('month', p.pay_date) > e.term_date)
