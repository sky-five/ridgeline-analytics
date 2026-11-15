-- StatCan rounds every count to a multiple of 3, moving it by at most 2. So the leaves of a region and year,
-- added up, can differ from the published total by at most 2 per leaf plus 2 for the total itself. Cells that
-- StatCan does not publish ('..') can only make the leaves smaller. Checked per region, year and status.
with leaves as (
    select fall_year, region_code, status_code, sum(enrolments) as leaves, count(*) as cells,
           count(*) filter (where is_not_available) as not_available
    from {{ ref('fct_enrolment') }}
    group by 1, 2, 3
)

select l.*, t.published_enrolments
from leaves as l
inner join {{ ref('stg_statcan__totals') }} as t using (fall_year, region_code, status_code)
where l.leaves > t.published_enrolments + 2 * (l.cells + 1)
   or (l.not_available = 0 and l.leaves < t.published_enrolments - 2 * (l.cells + 1))
