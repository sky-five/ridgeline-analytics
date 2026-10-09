select rep, count(*) as top_accounts_called,
       avg(case when called_within_3d then 1.0 else 0 end) as called_within_3d_rate
from main.fct_rep_followups
where first_call_at is not null
group by rep order by rep
