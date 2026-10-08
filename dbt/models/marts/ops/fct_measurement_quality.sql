select
    o.order_id,
    o.account_id,
    o.ordered_at,
    cast({{ dbt.date_trunc('month', 'o.ordered_at') }} as date) as ordered_month,
    a.region,
    o.roof_type,
    o.tier,
    cast({{ dbt.datediff('o.ordered_at', 'o.delivered_at', 'minute') }} as double) / 60 as turnaround_hours,  -- noqa: LT05
    o.redo_requested_at is not null as is_redo,
    o.redo_reason
from {{ ref('stg_app_db__measurement_orders') }} as o
inner join {{ ref('stg_app_db__accounts') }} as a on o.account_id = a.account_id
