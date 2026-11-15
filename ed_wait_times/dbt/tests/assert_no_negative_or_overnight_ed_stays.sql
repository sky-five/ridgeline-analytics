-- A visit ends after it starts and within two days.
select visit_id, los_hours
from {{ ref('stg_ed__visits') }}
where los_hours <= 0 or los_hours > 48
