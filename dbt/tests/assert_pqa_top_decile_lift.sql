-- The score must earn its keep: on the held-out 2026 cohorts, the top 10% by score should convert
-- at least 2.5x the average. Returns a row (fails) if it doesn't.
with test_set as (
    select
        is_paid_60d,
        ntile(10) over (order by score_model) as test_decile
    from {{ ref('fct_pqa_scores') }}
    where split = 'test'
),

rates as (
    select
        avg(case when is_paid_60d then 1.0 else 0.0 end) as overall_rate,
        avg(case when test_decile = 10 then (case when is_paid_60d then 1.0 else 0.0 end) end) as top_rate
    from test_set
)

select *
from rates
where top_rate < 2.5 * overall_rate
