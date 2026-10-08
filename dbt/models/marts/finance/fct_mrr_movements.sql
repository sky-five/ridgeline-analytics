select
    change_id,
    account_id,
    changed_at,
    movement_date,
    movement_month,
    movement_type,
    cast(mrr_before as {{ dbt.type_numeric() }}) as mrr_before,
    cast(mrr_after as {{ dbt.type_numeric() }}) as mrr_after,
    cast(mrr_delta as {{ dbt.type_numeric() }}) as mrr_delta
from {{ ref('int_mrr_movements') }}
