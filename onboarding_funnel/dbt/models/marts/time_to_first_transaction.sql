-- Days from first starting an application to the first transaction, for people in mature cohorts who
-- activated within the window.
select
    program,
    count(*) as activated,
    median(days_to_first_transaction) as median_days,
    quantile_cont(days_to_first_transaction, 0.9) as p90_days,
    avg(case when days_to_first_transaction <= 1 then 1 else 0 end) as share_within_1_day,
    avg(case when days_to_first_transaction <= 7 then 1 else 0 end) as share_within_7_days
from {{ ref('fct_applications') }}
where is_mature and is_activated
group by program
order by program
