-- One row per block (room-day), with every minute count the utilisation metrics are built from.
-- credited_released_minutes: the block's minutes if it was released at least 72 hours ahead (the usual rule
-- for crediting a service), else 0. Short-notice releases stay in the owner's denominator.
-- is_owner_booked: the owning service booked at least one case (its surgeon was not away).
-- period: before or after the auto-release rule started.
with case_minutes as (
    select
        block_id,
        sum(case when is_owner_case then in_block_minutes else 0 end) as owner_in_block_minutes,
        sum(case when is_owner_case then turnover_before_minutes else 0 end) as owner_turnover_minutes,
        sum(case when not is_owner_case then in_block_minutes else 0 end) as reused_in_block_minutes,
        count(case when is_owner_case then 1 end) as owner_booked_cases,
        count(case when not is_cancelled then 1 end) as completed_cases,
        count(case when is_cancelled then 1 end) as cancelled_cases
    from {{ ref('fct_cases') }}
    group by block_id
)

select
    b.block_id,
    b.block_date,
    date_trunc('week', b.block_date) as block_week,
    case when b.block_date >= date '{{ var("policy_start") }}' then 'after' else 'before' end as period,
    b.room_id,
    b.owner_service_id,
    b.allocated_minutes,
    r.block_id is not null as is_released,
    r.release_type,
    r.notice_hours,
    case when r.notice_hours >= 72 then b.allocated_minutes else 0 end as credited_released_minutes,
    case when r.block_id is not null then b.allocated_minutes else 0 end as released_minutes,
    coalesce(m.owner_in_block_minutes, 0) as owner_in_block_minutes,
    coalesce(m.owner_turnover_minutes, 0) as owner_turnover_minutes,
    coalesce(m.reused_in_block_minutes, 0) as reused_in_block_minutes,
    coalesce(m.owner_booked_cases, 0) > 0 as is_owner_booked,
    coalesce(m.completed_cases, 0) as completed_cases,
    coalesce(m.cancelled_cases, 0) as cancelled_cases
from {{ ref('stg_or__blocks') }} as b
left join {{ ref('stg_or__releases') }} as r on b.block_id = r.block_id
left join case_minutes as m on b.block_id = m.block_id
