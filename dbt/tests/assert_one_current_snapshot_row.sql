-- SCD2 integrity: each subscription has exactly one current version in the snapshot.
select subscription_id, count(*) as current_rows
from {{ ref('snap_subscriptions') }}
where dbt_valid_to is null
group by subscription_id
having count(*) <> 1
