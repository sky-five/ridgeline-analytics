-- The first time each account reached each product milestone.
select
    account_id,
    min(case when event_type = 'measurement_ordered' then occurred_at end) as first_measurement_at,
    min(case when event_type = 'proposal_sent' then occurred_at end) as first_proposal_at,
    min(case when event_type = 'proposal_signed' then occurred_at end) as first_signed_at
from {{ ref('stg_product_events__events') }}
group by account_id
