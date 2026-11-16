-- Today's open claims = yesterday's + opened today - closed today.
select * from (
    select
        *,
        lag(open_backlog) over (partition by site, line order by day) as yesterday
    from {{ ref('fct_claims_day') }}
)
where yesterday is not null and open_backlog != yesterday + claims_opened - claims_closed
