-- A block's used minutes (cases plus the turnovers between them) never exceed the block, and a block's own
-- service has no cases in a block it released (released time is someone else's or idle).
select block_id
from {{ ref('fct_blocks') }}
where owner_in_block_minutes + owner_turnover_minutes + reused_in_block_minutes > allocated_minutes
    or (is_released and owner_in_block_minutes > 0)
    or (not is_released and reused_in_block_minutes > 0)
