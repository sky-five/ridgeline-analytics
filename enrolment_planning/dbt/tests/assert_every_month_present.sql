-- 140 months, January 2015 to August 2026, for every study level in the all-Canada series.
select study_level, count(distinct permit_month) as months
from {{ ref('study_permits_canada_month') }}
group by 1
having count(distinct permit_month) <> 140 or min(permit_month) <> date '2015-01-01'
    or max(permit_month) <> date '2026-08-01'
