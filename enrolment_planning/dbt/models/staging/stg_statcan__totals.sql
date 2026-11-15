select
    cast(fall_year as integer) as fall_year,
    region as region_code,
    status as status_code,
    cast(enrolments as integer) as published_enrolments
from {{ source('raw_public', 'statcan_totals') }}
