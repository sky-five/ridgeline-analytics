-- Open pipeline by the quarter it is expected to close, against the average won per quarter over the
-- last four complete quarters (a stand-in for a quota, which the CRM does not hold).
{% set as_of = "cast('" ~ var('as_of_date') ~ "' as date)" %}
with opps as (
    select * from {{ ref('fct_opportunities') }}
),

baseline as (
    select sum(amount_usd) / 4 as avg_won_per_quarter
    from opps
    where
        is_won
        and corrected_close_date >= date_trunc('quarter', {{ as_of }}) - interval 12 month
        and corrected_close_date < date_trunc('quarter', {{ as_of }})
)

select
    cast(date_trunc('quarter', o.recorded_close_date) as date) as close_quarter,
    count(*) as open_deals,
    sum(o.amount_usd) as open_pipeline_usd,
    sum(o.amount_usd * o.probability / 100) as weighted_pipeline_usd,
    round(b.avg_won_per_quarter, 0) as avg_won_per_quarter_usd,
    round(sum(o.amount_usd) / b.avg_won_per_quarter, 2) as coverage_ratio
from opps as o
cross join baseline as b
where not o.is_closed
group by close_quarter, b.avg_won_per_quarter
order by close_quarter
