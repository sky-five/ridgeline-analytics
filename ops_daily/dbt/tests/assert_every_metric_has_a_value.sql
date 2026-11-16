-- Seven metrics for every day, site and line.
select day, site, line from {{ ref('ops_metric_day') }} group by all having count(*) != 7
