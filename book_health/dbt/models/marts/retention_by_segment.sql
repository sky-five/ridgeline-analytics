-- Retention over the last 12 months to the as-of date by province, product and channel, with the mean rate
-- change offered at those renewals.
select
    province,
    product,
    channel,
    sum(renewals_due)::int as renewals_due,
    sum(renewed)::int as renewed,
    round(sum(renewed) / nullif(sum(renewals_due), 0), 4)::double as retention,
    round(sum(sum_rate_change) / nullif(sum(renewals_due), 0), 4)::double as mean_rate_change
from {{ ref('fct_segment_month') }}
where month_start > date_trunc('month', date '{{ var("as_of") }}') - interval 12 month
group by all
