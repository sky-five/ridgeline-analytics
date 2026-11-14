-- Every mature person who did not activate has exactly one drop-off reason.
select d.program
from (select program, sum(applicants) as n from {{ ref('drop_off_reasons') }} group by program) as d
inner join {{ ref('funnel_by_program') }} as p on d.program = p.program
where d.n != p.started - p.activated
