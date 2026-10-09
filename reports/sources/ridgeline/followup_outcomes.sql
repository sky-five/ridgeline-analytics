select case when called_within_3d then 'Called within 3 days' else 'Not called within 3 days' end as follow_up,
       count(*) as accounts, avg(case when converted_60d then 1.0 else 0 end) as paid_60d_rate
from main.fct_rep_followups
where converted_60d is not null
group by 1
