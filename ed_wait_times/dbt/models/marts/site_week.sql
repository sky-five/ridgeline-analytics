-- One row per site, week (Monday to Sunday) and patient group. The 90th percentile is taken over the week's
-- patients, not averaged from daily percentiles. A group with fewer than min_weekly_patients patients is not
-- reported, the way Ontario leaves out figures from too few patients.
with weekly as (
    select
        site_id,
        week_start,
        patient_group,
        max(target_hours) as target_hours,
        count(*) as patients,
        quantile_cont(los_hours, 0.9) as p90_los_hours,
        avg(within_target::int) as share_within_target
    from {{ ref('stg_ed__visits') }}
    group by 1, 2, 3
),

beds as (
    select
        site_id,
        cast(date_trunc('week', census_date) as date) as week_start,
        avg(occupancy_rate) as mean_bed_occupancy,
        min(staffed_beds) as min_staffed_beds
    from {{ ref('stg_ed__bed_census') }}
    group by 1, 2
)

select
    weekly.*,
    beds.mean_bed_occupancy,
    beds.min_staffed_beds,
    weekly.patients >= {{ var('min_weekly_patients') }} as reportable,
    weekly.patients >= {{ var('min_weekly_patients') }} and weekly.p90_los_hours > weekly.target_hours as breached
from weekly
left join beds on weekly.site_id = beds.site_id and weekly.week_start = beds.week_start
