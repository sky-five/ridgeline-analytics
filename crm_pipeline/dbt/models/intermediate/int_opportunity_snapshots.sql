-- The pipeline as it stood on the first day of each quarter, rebuilt from the history:
-- each deal's latest history row before that day, kept if the deal was still open.
with history as (
    select * from {{ ref('stg_crm__opportunity_history') }}
),

quarters as (
    select cast(q as date) as snapshot_date
    from range(
        date_trunc('quarter', (select min(changed_at) from history)) + interval 3 month,
        date_trunc('quarter', cast('{{ var("as_of_date") }}' as date)) + interval 3 month,
        interval 3 month
    ) as t (q)
),

latest as (
    select
        q.snapshot_date,
        h.*,
        row_number() over (
            partition by q.snapshot_date, h.opportunity_id order by h.changed_at desc, h.history_id desc
        ) as rn
    from quarters as q
    inner join history as h on h.changed_at < q.snapshot_date
)

select
    snapshot_date,
    opportunity_id,
    stage,
    open_stage_rank,
    amount_usd,
    close_date,
    probability
from latest
where rn = 1 and not is_closed
