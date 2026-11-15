-- The finance mart: daily P&L per account. Market P&L marks yesterday's holdings (adjusted for any split
-- going ex today) at today's close; trades happen at the close, so they add no P&L. Whatever moves equity
-- and is not market P&L, a deposit or interest is left as unexplained.
with days as (
    select price_date as as_of_date, lag(price_date) over (order by price_date) as prior_date
    from (select distinct price_date from {{ ref('stg_margin__prices') }})
),

market as (
    select
        d.as_of_date,
        y.account_id,
        sum(y.quantity * coalesce(ca.ratio, 1)::decimal(9, 4) * px.close - y.market_value) as market_pnl
    from days as d
    inner join {{ ref('fct_position_day') }} as y on d.prior_date = y.as_of_date
    inner join {{ ref('stg_margin__prices') }} as px on d.as_of_date = px.price_date and y.symbol = px.symbol
    left join {{ source('raw_margin', 'corporate_actions') }} as ca
        on y.symbol = ca.symbol and d.as_of_date = ca.ex_date and ca.action = 'split'
    group by d.as_of_date, y.account_id
),

activity as (
    select
        as_of_date,
        account_id,
        sum(amount::decimal(18, 2)) filter (where kind = 'deposit') as deposits,
        sum(amount::decimal(18, 2)) filter (where kind = 'interest') as interest
    from {{ source('raw_margin', 'cash_activity') }}
    group by as_of_date, account_id
),

equity as (
    select
        a.as_of_date,
        a.account_id,
        a.equity,
        a.equity - lag(a.equity) over (partition by a.account_id order by a.as_of_date) as equity_change
    from {{ ref('fct_account_day') }} as a
)

select
    e.as_of_date,
    e.account_id,
    e.equity_change,
    coalesce(m.market_pnl, 0) as market_pnl,
    coalesce(ac.deposits, 0) as deposits,
    coalesce(ac.interest, 0) as interest,
    round(e.equity_change - coalesce(m.market_pnl, 0) - coalesce(ac.deposits, 0) - coalesce(ac.interest, 0), 2)
        as unexplained
from equity as e
inner join days as d on e.as_of_date = d.as_of_date
left join market as m on e.as_of_date = m.as_of_date and e.account_id = m.account_id
left join activity as ac on e.as_of_date = ac.as_of_date and e.account_id = ac.account_id
where d.prior_date is not null
