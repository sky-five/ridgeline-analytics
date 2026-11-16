select day, site, line from {{ ref('fct_ops_day') }} group by all having count(*) > 1
