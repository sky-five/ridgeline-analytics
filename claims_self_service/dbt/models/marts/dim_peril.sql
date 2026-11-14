-- One row per peril (cause of loss).
select
    peril_id,
    line_of_business,
    peril_group,
    expected_cycle_days
from {{ ref('stg_claims__perils') }}
