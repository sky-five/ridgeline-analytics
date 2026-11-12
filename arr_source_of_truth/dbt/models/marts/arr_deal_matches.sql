-- Each closed-won deal matched to the billing change it should have started, and why the two differ.
--
-- Match rule: same customer, a billing change of the right kind (new or win-back -> a new subscription,
-- expansion -> a plan upgrade) that took effect 0-30 days after the close date; the nearest one wins.
-- If two deals point at the same change, the earlier deal keeps it.
with deals as (
    select * from {{ ref('stg_crm__won_deals') }}
),

changes as (
    select * from {{ ref('stg_billing__subscription_changes') }} where is_sales_led
),

candidates as (
    select
        d.deal_id,
        c.change_key,
        row_number() over (
            partition by d.deal_id order by c.effective_on - d.close_date, c.effective_on, c.change_key
        ) as nearest
    from deals as d
    inner join changes as c
        on d.customer_id = c.customer_id
        and c.reason = case when d.deal_type = 'expansion' then 'upgrade' else 'new' end
        and c.effective_on between d.close_date and d.close_date + interval 30 day
),

claimed as (
    select
        cand.deal_id,
        cand.change_key,
        row_number() over (partition by cand.change_key order by d.close_date, d.deal_id) as claim_order
    from candidates as cand
    inner join deals as d on cand.deal_id = d.deal_id
    where cand.nearest = 1
),

matched as (
    select d.*, c.change_key, c.effective_on, 12 * c.delta_mrr_cents as billed_arr_cents
    from deals as d
    left join claimed as cl on d.deal_id = cl.deal_id and cl.claim_order = 1
    left join changes as c on cl.change_key = c.change_key
)

select
    m.deal_id,
    m.customer_id,
    m.deal_type,
    m.close_date,
    m.month_start as close_month,
    m.booked_arr_cents,
    m.change_key,
    m.effective_on,
    cast(date_trunc('month', m.effective_on) as date) as billed_month,
    m.billed_arr_cents,
    case
        when m.change_key is null and exists (
            select 1 from matched as o
            where o.change_key is not null
                and o.customer_id = m.customer_id
                and o.deal_type = m.deal_type
                and o.booked_arr_cents = m.booked_arr_cents
                and m.close_date between o.close_date and o.close_date + interval 14 day
        ) then 'duplicate'
        when m.change_key is null and m.close_date > date '{{ var("as_of_date") }}' - interval 30 day
            then 'awaiting_billing'
        when m.change_key is null then 'won_not_billed'
        when m.booked_arr_cents = m.billed_arr_cents then 'agrees'
        when 12 * m.booked_arr_cents = 10 * m.billed_arr_cents then 'annual_at_billed'
        else 'amount_differs'
    end as status
from matched as m
