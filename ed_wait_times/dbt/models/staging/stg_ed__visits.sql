-- One row per visit with its hours in the ED and the target that applies to it. The groups and targets follow
-- Ontario's public definitions: admitted patients 8 hours; patients sent home 8 hours if high urgency
-- (triage levels 1 to 3), 4 hours if low urgency (levels 4 and 5).
with v as (
    select
        visit_id,
        site_id,
        triage_at,
        left_ed_at,
        triage_level,
        disposition,
        cast(triage_at as date) as visit_date,
        cast(date_trunc('week', triage_at) as date) as week_start,
        date_diff('minute', triage_at, left_ed_at) / 60.0 as los_hours
    from {{ source('raw_ed', 'visits') }}
)

select
    *,
    case
        when disposition = 'admitted' then 'admitted'
        when triage_level <= 3 then 'high_urgency_sent_home'
        else 'low_urgency_sent_home'
    end as patient_group,
    case when disposition = 'discharged' and triage_level >= 4 then 4 else 8 end as target_hours,
    los_hours <= case when disposition = 'discharged' and triage_level >= 4 then 4 else 8 end as within_target
from v
