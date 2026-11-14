-- One row per booked case.
-- in_room_minutes: wheels in to wheels out. in_block_minutes: the part inside the block's 07:30-15:30 window,
-- which is what utilisation counts (overrun is not extra capacity).
-- turnover_before_minutes: the gap since the previous completed case in the same block, inside the window.
-- is_owner_case: the block's owning service ran it; otherwise it ran in a block the owner released.
with completed as (
    select
        c.*,
        b.owner_service_id,
        b.starts_at as block_starts_at,
        b.ends_at as block_ends_at,
        lag(c.wheels_out) over (partition by c.block_id order by c.wheels_in) as previous_wheels_out
    from {{ ref('stg_or__cases') }} as c
    inner join {{ ref('stg_or__blocks') }} as b on c.block_id = b.block_id
)

select
    case_id,
    block_id,
    room_id,
    case_date,
    service_id,
    owner_service_id,
    service_id = owner_service_id as is_owner_case,
    booked_minutes,
    status,
    status = 'cancelled' as is_cancelled,
    wheels_in,
    wheels_out,
    -- DuckDB's greatest() and least() skip nulls, so cancelled cases and first cases are handled explicitly.
    case when status = 'completed' then datediff('minute', wheels_in, wheels_out) else 0 end as in_room_minutes,
    case when status = 'completed' then greatest(0, datediff(
        'minute', greatest(wheels_in, block_starts_at), least(wheels_out, block_ends_at)
    )) else 0 end as in_block_minutes,
    case when status = 'completed' and previous_wheels_out is not null then greatest(0, datediff(
        'minute', least(previous_wheels_out, block_ends_at), least(wheels_in, block_ends_at)
    )) else 0 end as turnover_before_minutes
from completed
