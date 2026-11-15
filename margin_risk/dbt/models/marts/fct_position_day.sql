-- One row per account, security and day, marked at the close with its maintenance requirement. A holding over
-- the concentration share of the account's market value needs at least the concentration rate.
with marked as (
    select
        p.as_of_date,
        p.account_id,
        p.symbol,
        s.sector,
        p.quantity,
        px.close,
        s.maintenance_rate as base_rate,
        round(p.quantity * px.close, 2) as market_value
    from {{ ref('stg_margin__positions') }} as p
    inner join {{ ref('stg_margin__prices') }} as px on p.symbol = px.symbol and p.as_of_date = px.price_date
    inner join {{ source('raw_margin', 'securities') }} as s on p.symbol = s.symbol
),

shared as (
    select
        *,
        market_value / nullif(sum(market_value) over (partition by as_of_date, account_id), 0) as position_share
    from marked
)

select
    *,
    case
        when position_share > {{ var('concentration_share') }}
            then greatest(base_rate, {{ var('concentration_rate') }})
        else base_rate
    end as applied_rate,
    market_value * (
        case
            when position_share > {{ var('concentration_share') }}
                then greatest(base_rate, {{ var('concentration_rate') }})
            else base_rate
        end
    ) as requirement
from shared
