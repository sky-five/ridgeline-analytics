-- At most three items a day, at most one per site and line, and every item is a flagged metric.
select day from {{ ref('ops_watchlist') }} group by day having count(*) > 3 or count(distinct site || line) != count(*)
union all
select w.day from {{ ref('ops_watchlist') }} as w
left join {{ ref('ops_flags') }} as f using (day, site, line, metric)
where not coalesce(f.flagged, false)
