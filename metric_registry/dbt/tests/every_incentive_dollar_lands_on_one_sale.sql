-- Program spend and the per-sale roll-up must hold the same dollars.
select 1
from (select sum(amount) as total from {{ ref('fct_incentive_applications') }}) as a,
     (select sum(incentive_amount) as total from {{ ref('fct_sales') }}) as s
where abs(a.total - s.total) >= 0.01
