-- The utilisation metrics per week, whole suite.
select
    block_week,
    min(period) as period,
    {{ utilisation_columns() }}
from {{ ref('fct_blocks') }}
group by block_week
