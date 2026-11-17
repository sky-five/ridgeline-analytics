-- One row per call, caller and tracking number as ten digits, the campaign from the tracking number when it has one.
select
    k.call_id,
    k.started_at::timestamp as started_at,
    {{ phone10('k.caller') }} as caller_phone,
    {{ phone10('k.tracking_number') }} as tracking_phone,
    k.duration_s::int as duration_s,
    {{ click_id('k.click_id') }} as click_id,
    t.campaign_id as tracking_campaign_id
from {{ source('bronze', 'calls') }} as k
left join {{ ref('slv_tracking_numbers') }} as t
    on {{ phone10('k.tracking_number') }} = t.tracking_phone
qualify row_number() over (partition by k.call_id order by k._batch_id desc) = 1
