-- From what sales booked in the CRM to what the ARR bridge shows, per month, every step in its own column.
--
--   crm_booked + duplicates + won_not_billed + awaiting_billing + amount_fixes + timing + missing_deals
--     = billing_sales_led                       (new subscriptions and upgrades, from billing)
--   billing_sales_led + seat_changes + cancellations
--     = net_change                              (= closing - opening ARR in arr_bridge)
with deals as (
    select * from {{ ref('arr_deal_matches') }}
),

changes as (
    select *, 12 * delta_mrr_cents as delta_arr_cents from {{ ref('stg_billing__subscription_changes') }}
),

matched_changes as (
    select change_key from deals where change_key is not null
),

crm as (
    select
        close_month as month_start,
        sum(booked_arr_cents) as crm_booked,
        -sum(booked_arr_cents) filter (where status = 'duplicate') as duplicates,
        -sum(booked_arr_cents) filter (where status = 'won_not_billed') as won_not_billed,
        -sum(booked_arr_cents) filter (where status = 'awaiting_billing') as awaiting_billing,
        sum(billed_arr_cents - booked_arr_cents) filter (where change_key is not null) as amount_fixes,
        -sum(billed_arr_cents) filter (where change_key is not null and billed_month <> close_month) as timing_out
    from deals
    group by close_month
),

timing_in as (
    select billed_month as month_start, sum(billed_arr_cents) as timing_in
    from deals
    where change_key is not null and billed_month <> close_month
    group by billed_month
),

billing as (
    select
        c.month_start,
        sum(c.delta_arr_cents) filter (where c.is_sales_led and mc.change_key is null) as missing_deals,
        sum(c.delta_arr_cents) filter (where c.is_sales_led) as billing_sales_led,
        sum(c.delta_arr_cents) filter (where c.reason in ('seats_up', 'seats_down')) as seat_changes,
        sum(c.delta_arr_cents) filter (where c.reason in ('churn', 'cancel_refund')) as cancellations,
        sum(c.delta_arr_cents) as net_change
    from changes as c
    left join matched_changes as mc on c.change_key = mc.change_key
    group by c.month_start
)

select
    m.month_start,
    cast(coalesce(crm.crm_booked, 0) as bigint) as crm_booked_cents,
    cast(coalesce(crm.duplicates, 0) as bigint) as duplicates_cents,
    cast(coalesce(crm.won_not_billed, 0) as bigint) as won_not_billed_cents,
    cast(coalesce(crm.awaiting_billing, 0) as bigint) as awaiting_billing_cents,
    cast(coalesce(crm.amount_fixes, 0) as bigint) as amount_fixes_cents,
    cast(coalesce(crm.timing_out, 0) + coalesce(ti.timing_in, 0) as bigint) as timing_cents,
    cast(coalesce(b.missing_deals, 0) as bigint) as missing_deals_cents,
    cast(coalesce(b.billing_sales_led, 0) as bigint) as billing_sales_led_cents,
    cast(coalesce(b.seat_changes, 0) as bigint) as seat_changes_cents,
    cast(coalesce(b.cancellations, 0) as bigint) as cancellations_cents,
    cast(coalesce(b.net_change, 0) as bigint) as net_change_cents
from {{ ref('arr_months') }} as m
left join crm on m.month_start = crm.month_start
left join timing_in as ti on m.month_start = ti.month_start
left join billing as b on m.month_start = b.month_start
