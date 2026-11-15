-- One row per month, region (territories one by one), study level. CA rows are IRCC's all-Canada rows.
select
    cast(month as date) as permit_month,
    region as region_code,
    region_name,
    study_level,
    cast(permits as integer) as permits,
    suppressed as is_suppressed
from {{ source('raw_public', 'ircc_study_permits') }}
