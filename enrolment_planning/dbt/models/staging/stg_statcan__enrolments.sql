-- One row per fall year, region, ISCED level, institution type, program group and status of student.
select
    cast(fall_year as integer) as fall_year,
    region as region_code,
    isced as isced_code,
    institution as institution_code,
    program as program_code,
    status as status_code,
    cast(enrolments as integer) as enrolments,
    enrolments is null as is_not_available
from {{ source('raw_public', 'statcan_enrolments') }}
