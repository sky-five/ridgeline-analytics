-- Per region and fall year: enrolments by status from the fact, the published totals next to them, and the
-- international share. Leaves carry StatCan's random rounding, so the sums differ from the totals by a few.
with leaves as (
    select
        fall_year,
        region_code,
        sum(enrolments) filter (where status_code = 'CAN') as canadian,
        sum(enrolments) filter (where status_code = 'INT') as international,
        sum(enrolments) filter (where status_code = 'NR') as not_reported,
        sum(enrolments) as total,
        count(*) filter (where is_not_available) as cells_not_available
    from {{ ref('fct_enrolment') }}
    group by 1, 2
),

published as (
    select
        fall_year,
        region_code,
        max(published_enrolments) filter (where status_code = 'ALL') as published_total,
        max(published_enrolments) filter (where status_code = 'INT') as published_international
    from {{ ref('stg_statcan__totals') }}
    group by 1, 2
)

select
    l.*,
    p.published_total,
    p.published_international,
    l.international / nullif(l.total, 0) as international_share
from leaves as l
left join published as p using (fall_year, region_code)
