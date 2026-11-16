-- The three things to look at each day: of the flagged metrics, the furthest from its baseline per site and line
-- (one item per team), then the three teams furthest out. other_flags names the team's other flagged metrics.
with f as (select * from {{ ref('ops_flags') }} where flagged),

per_team as (
    select
        *,
        row_number() over (partition by day, site, line order by abs(score) desc, metric) as team_rank,
        string_agg(metric, ', ' order by abs(score) desc, metric) over (
            partition by day, site, line
        ) as team_flags
    from f
),

ranked as (
    select
        *,
        row_number() over (partition by day order by abs(score) desc, site, line) as rank
    from per_team
    where team_rank = 1
)

select
    day,
    rank,
    site,
    line,
    metric,
    value,
    baseline,
    score,
    nullif(trim(replace(', ' || team_flags || ', ', ', ' || metric || ', ', ', '), ', '), '') as other_flags
from ranked
where rank <= 3
