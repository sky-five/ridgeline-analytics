-- One row per weekday: the whole book, its risk and its P&L.
with book as (
    select
        as_of_date,
        count(*) as accounts,
        count(*) filter (where loan > 0) as borrowers,
        sum(market_value) as market_value,
        sum(loan) as loan,
        sum(equity) as equity,
        sum(requirement) as requirement,
        sum(collateral_value) filter (where loan > 0) / nullif(sum(loan), 0) as collateral_coverage,
        sum(loan) / nullif(sum(market_value * {{ var('initial_rate') }}) filter (where loan > 0), 0)
            as margin_utilisation,
        count(*) filter (where in_call) as accounts_in_call,
        sum(deficit) as total_deficit,
        count(*) filter (where is_concentrated and loan > 0) as concentrated_borrowers
    from {{ ref('fct_account_day') }}
    group by as_of_date
),

pnl as (
    select
        as_of_date,
        sum(market_pnl) as market_pnl,
        sum(deposits) as deposits,
        -sum(interest) as interest_income,
        sum(unexplained) as unexplained
    from {{ ref('fct_account_pnl_day') }}
    group by as_of_date
),

new_calls as (
    select call_date as as_of_date, count(*) as new_calls
    from {{ ref('margin_calls') }}
    group by call_date
)

select
    b.*,
    coalesce(n.new_calls, 0) as new_calls,
    p.market_pnl,
    p.deposits,
    p.interest_income,
    p.unexplained
from book as b
left join pnl as p on b.as_of_date = p.as_of_date
left join new_calls as n on b.as_of_date = n.as_of_date
