-- The weekly table counts every visit once.
select site_id, sum(patients) as weekly, (select count(*) from {{ ref('stg_ed__visits') }} as v
    where v.site_id = w.site_id) as visits
from {{ ref('site_week') }} as w
group by site_id
having sum(patients) != (select count(*) from {{ ref('stg_ed__visits') }} as v where v.site_id = w.site_id)
