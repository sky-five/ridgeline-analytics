-- Classify each subscription change by how it moved MRR.
with changes as (
    select * from {{ ref('stg_app_db__subscription_changes') }}
)

select
    change_id,
    account_id,
    changed_at,
    cast(changed_at as date) as movement_date,
    cast({{ dbt.date_trunc('month', 'changed_at') }} as date) as movement_month,
    case
        when mrr_before = 0 and mrr_after > 0 and change_type = 'reactivate' then 'reactivation'
        when mrr_before = 0 and mrr_after > 0 then 'new'
        when mrr_before > 0 and mrr_after = 0 then 'churn'
        when mrr_after > mrr_before then 'expansion'
        when mrr_after < mrr_before then 'contraction'
    end as movement_type,
    mrr_before,
    mrr_after,
    mrr_after - mrr_before as mrr_delta
from changes
where mrr_after <> mrr_before
