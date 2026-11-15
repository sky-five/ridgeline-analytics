-- The provinces added up can be below IRCC's all-Canada row (permits with no province stated, suppressed
-- cells) but never above it by more than the rounding: each cell is a multiple of 5, so off by at most 2.5.
with provinces as (
    select permit_month, study_level, sum(permits) as permits, count(*) as cells
    from {{ ref('stg_ircc__study_permits') }}
    where region_code <> 'CA'
    group by 1, 2
)

select p.*, c.permits as canada
from provinces as p
inner join {{ ref('study_permits_canada_month') }} as c using (permit_month, study_level)
where p.permits > c.permits + 2.5 * (p.cells + 1)
