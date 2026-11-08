-- Back-test of a weighted-pipeline forecast. On the first day of each complete quarter, take the open
-- deals expected to close in that quarter and weight each by
--   (a) the probability the CRM gives its stage, and
--   (b) the share of deals at that stage that were won, from earlier quarter-start snapshots whose
--       outcome was known before this one (so the forecast never sees the future).
-- Compare both with what was really won in the quarter (by corrected close date).
{% set as_of = "cast('" ~ var('as_of_date') ~ "' as date)" %}
with snapshots as (
    select * from {{ ref('int_opportunity_snapshots') }}
),

opps as (
    select
        f.opportunity_id,
        f.is_won,
        f.amount_usd,
        f.corrected_close_date,
        c.closed_on
    from {{ ref('fct_opportunities') }} as f
    inner join {{ ref('int_opportunity_close_dates') }} as c on f.opportunity_id = c.opportunity_id
),

quarters as (
    select distinct snapshot_date
    from snapshots
    where snapshot_date + interval 3 month <= {{ as_of }} + interval 1 day
),

stage_rates as (
    -- for each quarter, win rates per stage learned only from outcomes known before it started
    select
        q.snapshot_date,
        s.stage,
        count(*) filter (where o.is_won) / count(*) as learned_win_rate,
        count(*) as learned_from
    from quarters as q
    inner join snapshots as s on s.snapshot_date < q.snapshot_date
    inner join opps as o on s.opportunity_id = o.opportunity_id and o.closed_on < q.snapshot_date
    group by q.snapshot_date, s.stage
),

in_quarter as (
    select
        s.*,
        o.is_won and o.corrected_close_date < s.snapshot_date + interval 3 month as won_in_quarter,
        r.learned_win_rate
    from snapshots as s
    inner join quarters as q on s.snapshot_date = q.snapshot_date
    inner join opps as o on s.opportunity_id = o.opportunity_id
    left join stage_rates as r on s.snapshot_date = r.snapshot_date and s.stage = r.stage
    where s.close_date >= s.snapshot_date and s.close_date < s.snapshot_date + interval 3 month
),

forecast as (
    select
        snapshot_date,
        count(*) as deals_in_forecast,
        sum(amount_usd * probability / 100) as forecast_crm_probability_usd,
        sum(amount_usd * learned_win_rate) as forecast_learned_rates_usd,
        bool_and(learned_win_rate is not null) as has_learned_rates,
        sum(case when won_in_quarter then amount_usd else 0 end) as won_from_forecast_deals_usd
    from in_quarter
    group by snapshot_date
),

actual as (
    select
        q.snapshot_date,
        sum(o.amount_usd) as won_usd
    from quarters as q
    inner join opps as o
        on
            o.is_won
            and o.corrected_close_date >= q.snapshot_date
            and o.corrected_close_date < q.snapshot_date + interval 3 month
    group by q.snapshot_date
)

select
    cast(f.snapshot_date as date) as quarter_start,
    f.deals_in_forecast,
    round(f.forecast_crm_probability_usd, 0) as forecast_crm_probability_usd,
    case when f.has_learned_rates then round(f.forecast_learned_rates_usd, 0) end as forecast_learned_rates_usd,
    f.won_from_forecast_deals_usd,
    a.won_usd as actual_won_usd,
    round(f.forecast_crm_probability_usd / a.won_usd - 1, 3) as error_crm_probability,
    case when f.has_learned_rates then round(f.forecast_learned_rates_usd / a.won_usd - 1, 3) end
        as error_learned_rates
from forecast as f
inner join actual as a on f.snapshot_date = a.snapshot_date
order by quarter_start
