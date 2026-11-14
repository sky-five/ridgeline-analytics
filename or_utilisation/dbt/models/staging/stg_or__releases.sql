select
    r.block_id,
    cast(r.released_at as timestamp) as released_at,
    r.release_type,
    datediff('minute', cast(r.released_at as timestamp), cast(b.starts_at as timestamp)) / 60.0 as notice_hours
from {{ source('raw_or', 'releases') }} as r
inner join {{ source('raw_or', 'blocks') }} as b on r.block_id = b.block_id
