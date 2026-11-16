-- The flag rule. Each day's value is compared with the same weekday in the previous {{ var('baseline_weeks') }}
-- weeks: baseline = their median, spread = 1.4826 x their median absolute deviation (a standard deviation that a
-- single odd day can't move), floored at the metric's min_spread and, for counts, at the square root of the
-- baseline. A day is flagged when it is at least {{ var('flag_score') }} spreads away, the move is at least the
-- metric's minimum change, and it is in the bad direction (either way for metrics with no good direction).
with m as (select * from {{ ref('ops_metric_day') }}),

base as (
    select
        *,
        count(value) over w as baseline_days,
        median(value) over w as baseline,
        mad(value) over w as mad
    from m
    window w as (
        partition by site, line, metric, dayofweek(day) order by day
        rows between {{ var('baseline_weeks') }} preceding and 1 preceding
    )
),

scored as (
    select
        b.day,
        b.site,
        b.line,
        b.metric,
        b.value,
        b.baseline,
        b.baseline_days,
        d.good_direction,
        greatest(
            1.4826 * b.mad, d.min_spread, case when d.kind = 'count' then sqrt(greatest(b.baseline, 1)) else 0 end
        ) as spread,
        greatest(d.min_change_abs, d.min_change_rel * abs(b.baseline)) as min_change
    from base as b
    inner join {{ ref('metric_definitions') }} as d using (metric)
)

select
    *,
    (value - baseline) / spread as score,
    coalesce(
        baseline_days = {{ var('baseline_weeks') }}
        and abs(value - baseline) >= {{ var('flag_score') }} * spread
        and abs(value - baseline) >= min_change
        and case good_direction when 'up' then value < baseline when 'down' then value > baseline else true end,
        false
    ) as flagged
from scored
