-- Every cent in the payroll export lands in exactly one group and month.
select 1
from (select sum(amount_cents) as total from {{ ref('stg_payroll__pay_lines') }}) as lines
cross join (select sum(gross_pay_cents) as total from {{ ref('hr_group_months') }}) as groups
where lines.total <> groups.total
