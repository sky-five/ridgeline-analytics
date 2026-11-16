-- One row per day, site and line: the phone figures and the claims figures side by side, and the seven daily
-- metrics defined in seeds/metric_definitions.csv.
select
    k.day,
    k.site,
    k.line,
    p.offered,
    p.answered,
    p.abandoned,
    p.answered_within_60s,
    p.handle_seconds,
    p.staffed_hours,
    k.claims_opened,
    k.claims_closed,
    k.open_backlog,
    p.offered::double as calls_offered,
    p.answered_within_60s / nullif(p.offered, 0) as service_level,
    p.abandoned / nullif(p.offered, 0) as abandon_rate,
    p.handle_seconds / nullif(p.answered, 0) / 60 as avg_handle_minutes
from {{ ref('fct_claims_day') }} as k
inner join {{ ref('stg_ops__calls') }} as p using (day, site, line)
