-- Back-test of the 'ready for sales' score on 2026 signups it never saw
with t as (
    select is_paid_60d, ntile(10) over (order by score_model) as decile
    from main.fct_pqa_scores
    where split = 'test'
)
select decile, count(*) as accounts, avg(case when is_paid_60d then 1.0 else 0 end) as paid_60d_rate
from t group by decile order by decile
