-- One row per academic year. Enrolments are a fall snapshot: one date each institution picks between
-- 30 September and 1 December, so students who start in January or May are not in that year's count.
select
    fall_year,
    fall_year || '/' || (fall_year + 1) as academic_year,
    make_date(fall_year, 9, 30) as snapshot_window_start,
    make_date(fall_year, 12, 1) as snapshot_window_end
from (select distinct fall_year from {{ ref('stg_statcan__enrolments') }})
