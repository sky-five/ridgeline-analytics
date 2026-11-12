-- Every step from CRM bookings adds up to billing's new and upgrade ARR, to the cent, every month.
select *
from {{ ref('arr_booking_walk') }}
where crm_booked_cents + duplicates_cents + won_not_billed_cents + awaiting_billing_cents
    + amount_fixes_cents + timing_cents + missing_deals_cents <> billing_sales_led_cents
    or billing_sales_led_cents + seat_changes_cents + cancellations_cents <> net_change_cents
