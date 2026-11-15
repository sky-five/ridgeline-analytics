-- The risk mart: one row per account and day. Loan is the debit balance. A margin call is equity below the
-- maintenance requirement, the same as collateral value (market value less each holding's requirement) below
-- the loan.
with holdings as (
    select
        as_of_date,
        account_id,
        sum(market_value) as market_value,
        sum(requirement) as requirement,
        sum(market_value - requirement) as collateral_value,
        max(position_share) as top_position_share,
        arg_max(symbol, position_share) as top_symbol,
        count(*) as positions
    from {{ ref('fct_position_day') }}
    group by as_of_date, account_id
),

joined as (
    select
        c.as_of_date,
        c.account_id,
        a.account_type,
        a.margin_enabled,
        c.cash_balance,
        coalesce(h.positions, 0) as positions,
        coalesce(h.market_value, 0) as market_value,
        coalesce(h.requirement, 0) as requirement,
        coalesce(h.collateral_value, 0) as collateral_value,
        h.top_position_share,
        h.top_symbol,
        greatest(-c.cash_balance, 0) as loan
    from {{ ref('stg_margin__cash') }} as c
    inner join {{ source('raw_margin', 'accounts') }} as a on c.account_id = a.account_id
    left join holdings as h on c.as_of_date = h.as_of_date and c.account_id = h.account_id
)

select
    *,
    market_value + cash_balance as equity,
    market_value + cash_balance - requirement as excess,
    market_value + cash_balance < requirement as in_call,
    greatest(requirement - market_value - cash_balance, 0) as deficit,
    collateral_value / nullif(loan, 0) as collateral_coverage,
    loan / nullif(market_value * {{ var('initial_rate') }}, 0) as margin_utilisation,
    coalesce(top_position_share > {{ var('concentration_share') }}, false) as is_concentrated
from joined
