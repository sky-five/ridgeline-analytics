with tickets as (
    select * from {{ ref('stg_support__tickets') }}
),

-- was the account paying when it wrote in? (running MRR at the ticket time > 0)
paying as (
    select
        t.ticket_id,
        coalesce(sum(m.mrr_delta), 0) > 0 as is_paying_at_creation
    from tickets as t
    left join {{ ref('fct_mrr_movements') }} as m
        on t.account_id = m.account_id and t.created_at >= m.changed_at
    group by t.ticket_id
)

select
    t.ticket_id,
    t.account_id,
    t.created_at,
    cast({{ dbt.datediff('t.created_at', 't.first_reply_at', 'minute') }} as {{ dbt.type_bigint() }})  -- noqa: LT05
        as first_reply_minutes,
    cast({{ dbt.datediff('t.created_at', 't.solved_at', 'minute') }} as double) / 60 as resolution_hours,  -- noqa: LT05
    t.priority,
    t.channel,
    t.subject,
    t.body,
    t.status,
    p.is_paying_at_creation,
    th.churn_theme
from tickets as t
inner join paying as p on t.ticket_id = p.ticket_id
left join {{ ref('fct_ticket_themes') }} as th on t.ticket_id = th.ticket_id
