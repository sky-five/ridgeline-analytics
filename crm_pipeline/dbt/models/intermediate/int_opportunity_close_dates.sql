-- The close date a rep typed vs the day the deal really closed (closed_at, from the stage change).
-- A won deal closed early in a quarter is sometimes given the previous quarter's last day so it counts
-- toward that quarter's number. Reporting uses the corrected date.
select
    opportunity_id,
    close_date as recorded_close_date,
    cast(closed_at as date) as closed_on,
    coalesce(cast(closed_at as date), close_date) as corrected_close_date,
    coalesce(
        is_closed and date_trunc('quarter', close_date) < date_trunc('quarter', cast(closed_at as date)),
        false
    ) as is_backdated
from {{ ref('stg_crm__opportunities') }}
