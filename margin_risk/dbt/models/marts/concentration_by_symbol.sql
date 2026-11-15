-- Per security and day: how much of the collateral behind margin loans it is, and how many borrowers hold it
-- as more than the concentration share of their account.
with borrowers as (
    select as_of_date, account_id from {{ ref('fct_account_day') }} where loan > 0
),

held as (
    select p.*
    from {{ ref('fct_position_day') }} as p
    inner join borrowers as b on p.as_of_date = b.as_of_date and p.account_id = b.account_id
)

select
    as_of_date,
    symbol,
    any_value(sector) as sector,
    sum(market_value) as borrower_market_value,
    sum(market_value) / sum(sum(market_value)) over (partition by as_of_date) as share_of_borrower_value,
    count(*) as borrowers_holding,
    count(*) filter (where position_share > {{ var('concentration_share') }}) as borrowers_concentrated
from held
group by as_of_date, symbol
