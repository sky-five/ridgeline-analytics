-- New study permits per month, region and study level (the territories added up into TR). A suppressed
-- cell (1 to 4) counts as none here; permits_suppressed_cells says how many such cells went into a row.
select
    permit_month,
    region_code,
    study_level,
    coalesce(sum(permits), 0) as permits,
    count(*) filter (where is_suppressed) as permits_suppressed_cells
from {{ ref('stg_ircc__study_permits') }}
where region_code <> 'CA'
group by 1, 2, 3
