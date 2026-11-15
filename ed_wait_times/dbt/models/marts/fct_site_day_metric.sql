-- One row per site, day and metric: every daily number on one shape, so a page or a tool can ask for any of them
-- the same way. Days with no patients in a group get a count of 0 and no percentile.
with spine as (
    select s.site_id, c.census_date as day, c.staffed_beds, c.occupied_beds, c.occupancy_rate
    from {{ ref('dim_sites') }} as s
    inner join {{ ref('stg_ed__bed_census') }} as c on s.site_id = c.site_id
),

visits as (
    select
        site_id,
        visit_date as day,
        count(*) as ed_visits,
        count(*) filter (where patient_group = 'admitted') as admitted_visits,
        quantile_cont(los_hours, 0.9) filter (where patient_group = 'admitted') as p90_los_admitted_hours,
        avg(within_target::int) filter (where patient_group = 'admitted') as share_admitted_within_8h,
        quantile_cont(los_hours, 0.9) filter (where patient_group = 'low_urgency_sent_home')
            as p90_los_low_urgency_hours
    from {{ ref('stg_ed__visits') }}
    group by 1, 2
),

wide as (
    select
        spine.site_id,
        spine.day,
        coalesce(visits.ed_visits, 0)::double as ed_visits,
        coalesce(visits.admitted_visits, 0)::double as admitted_visits,
        visits.p90_los_admitted_hours,
        visits.share_admitted_within_8h,
        visits.p90_los_low_urgency_hours,
        spine.staffed_beds::double as staffed_beds,
        spine.occupied_beds::double as occupied_beds,
        spine.occupancy_rate as bed_occupancy_rate
    from spine
    left join visits on spine.site_id = visits.site_id and spine.day = visits.day
)

select site_id, day, metric, value
from wide
unpivot include nulls (
    value for metric in (
        ed_visits, admitted_visits, p90_los_admitted_hours, share_admitted_within_8h, p90_los_low_urgency_hours,
        staffed_beds, occupied_beds, bed_occupancy_rate
    )
)
