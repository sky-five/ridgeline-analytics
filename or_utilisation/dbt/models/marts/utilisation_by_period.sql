-- The utilisation metrics before and after the auto-release rule, on all blocks and on the blocks the owning
-- service booked (its surgeon was there). The rule only acts on blocks with nothing booked, so a change on
-- booked blocks is not the rule's doing.
select
    period,
    'all' as blocks_in_scope,
    {{ utilisation_columns() }}
from {{ ref('fct_blocks') }}
group by period

union all

select
    period,
    'owner_booked' as blocks_in_scope,
    {{ utilisation_columns() }}
from {{ ref('fct_blocks') }}
where is_owner_booked
group by period
