with source as (
    select * from {{ source('app_db', 'invoices') }}
)

select
    invoice_id,
    account_id,
    subscription_id,
    line_type,
    status,
    cast({{ to_utc('period_start_date') }} as date) as period_start_date,
    {{ to_utc('issued_at') }} as issued_at,
    {{ to_utc('paid_at') }} as paid_at,
    cast(amount_usd as {{ dbt.type_numeric() }}) as amount_usd,
    {{ to_utc('updated_at') }} as updated_at
from source
