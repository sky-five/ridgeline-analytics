-- One row per day, site and line: claims opened, claims closed and claims still open at the end of the day.
with days as (
    select unnest(generate_series(date '{{ var("first_day") }}', date '{{ var("as_of") }}', interval 1 day))::date
        as day
),

series as (select distinct site, line from {{ ref('stg_ops__claims') }}),

claims as (select * from {{ ref('stg_ops__claims') }})

select
    d.day,
    s.site,
    s.line,
    count(c.claim_id) filter (where c.opened_date = d.day)::int as claims_opened,
    count(c.claim_id) filter (where c.closed_date = d.day)::int as claims_closed,
    count(c.claim_id) filter (where c.closed_date is null or c.closed_date > d.day)::int as open_backlog
from days as d
cross join series as s
left join claims as c
    on
        s.site = c.site
        and s.line = c.line
        and c.opened_date <= d.day
        and (c.closed_date is null or c.closed_date >= d.day)
group by all
