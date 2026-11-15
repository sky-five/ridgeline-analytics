-- The star's fact: enrolments (program counts) per term, region, level, institution type, program and status.
select
    fall_year,
    region_code,
    isced_code,
    institution_code,
    program_code,
    status_code,
    enrolments,
    is_not_available
from {{ ref('stg_statcan__enrolments') }}
