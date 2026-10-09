select s.account_id, a.company_name, s.channel, s.crew_size, cast(s.signup_at as date) as signed_up,
       s.score_model, s.score_points, s.top_reasons
from main.fct_pqa_scores s
join main.dim_accounts a using (account_id)
where s.call_list_eligible
order by s.score_model desc
limit 50
