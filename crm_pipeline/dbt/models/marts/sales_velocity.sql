-- Sales velocity per segment: open deals x win rate x average won deal / days to win,
-- with the rates from new-business deals closed in the last 365 days before the as-of date.
{% set as_of = "cast('" ~ var('as_of_date') ~ "' as date)" %}
with opps as (
    select * from {{ ref('fct_opportunities') }}
    where opportunity_type = 'new_business'
),

closed as (
    select
        segment,
        count(*) as closed_deals,
        count(*) filter (where is_won) as won_deals,
        avg(amount_usd) filter (where is_won) as avg_won_usd,
        median(days_to_close) filter (where is_won) as median_days_to_win
    from opps
    where is_closed and corrected_close_date > {{ as_of }} - interval 365 day
    group by segment
),

open_now as (
    select segment, count(*) as open_deals
    from opps
    where not is_closed
    group by segment
)

select
    c.segment,
    coalesce(o.open_deals, 0) as open_deals,
    c.closed_deals,
    round(c.won_deals / c.closed_deals, 3) as win_rate,
    round(c.avg_won_usd, 0) as avg_won_usd,
    c.median_days_to_win,
    round(coalesce(o.open_deals, 0) * c.won_deals / c.closed_deals * c.avg_won_usd / c.median_days_to_win, 0)
        as velocity_usd_per_day
from closed as c
left join open_now as o on c.segment = o.segment
order by c.segment
