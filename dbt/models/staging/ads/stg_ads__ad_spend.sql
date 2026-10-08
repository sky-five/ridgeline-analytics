with source as (
    select * from {{ source('ads', 'ad_spend') }}
)

select
    spend_id,
    cast({{ to_utc('spend_date') }} as date) as spend_date,
    channel,
    campaign_id,
    cast(spend_usd as {{ dbt.type_numeric() }}) as spend_usd,
    cast(impressions as {{ dbt.type_int() }}) as impressions,
    cast(clicks as {{ dbt.type_int() }}) as clicks
from source
