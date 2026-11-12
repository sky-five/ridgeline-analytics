-- The walk's net change is the bridge's closing minus opening ARR, so CRM and the bridge tell one story.
select w.month_start
from {{ ref('arr_booking_walk') }} as w
inner join {{ ref('arr_bridge') }} as b on w.month_start = b.month_start
where w.net_change_cents <> b.closing_arr_cents - b.opening_arr_cents
