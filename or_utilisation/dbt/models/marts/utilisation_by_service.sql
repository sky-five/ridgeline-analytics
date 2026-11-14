-- The utilisation metrics per owning service, before and after the rule.
select
    owner_service_id,
    period,
    {{ utilisation_columns() }}
from {{ ref('fct_blocks') }}
group by owner_service_id, period
