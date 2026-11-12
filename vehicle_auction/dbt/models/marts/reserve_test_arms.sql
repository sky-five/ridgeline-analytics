-- The reserve-price test, one row per arm: first runs of vehicles consigned from 2026-04-06.
-- Outcome is the first run only, so relists (which lower the reserve again) cannot blur the comparison.
select
    test_arm as arm,
    count(*) as vehicles,
    count(*) filter (where first_run_offered) as offered,
    count(*) filter (where first_run_converted) as converted,
    count(*) filter (where first_run_converted) / count(*) filter (where first_run_offered) as conversion_rate,
    avg(first_run_proceeds_usd) filter (where first_run_offered) as proceeds_per_offered_usd,
    stddev_samp(first_run_proceeds_usd) filter (where first_run_offered) as proceeds_sd_usd,
    avg(first_run_proceeds_usd / book_value_usd) filter (where first_run_converted) as price_to_book_when_sold
from {{ ref('fct_vehicles') }}
where test_arm is not null
group by test_arm
