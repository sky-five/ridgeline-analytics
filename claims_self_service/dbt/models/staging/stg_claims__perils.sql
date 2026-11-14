select
    peril_id,
    line_of_business,
    peril_group,
    expected_cycle_days
from {{ source('raw_claims', 'perils') }}
