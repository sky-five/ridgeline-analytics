-- One row per lead: a person (client and ten-digit phone) however many CRM records they have. The campaign comes
-- from, in order: a click id on any of their CRM records, the click id call tracking saw on their call, the
-- tracking number they called. A lead none of those reach is unattributed (organic, or a click id that got lost).
with people as (
    select
        client,
        phone,
        min(created_at) as first_at,
        count(*) as crm_records,
        arg_min(source, created_at) as first_source,
        arg_min(click_id, created_at) filter (where click_id is not null) as crm_click_id,
        max(email) as email,
        max(case status when 'demo_done' then 3 when 'issued' then 2 when 'rejected' then 1 else 0 end)
            as status_rank
    from {{ ref('slv_crm_records') }}
    group by client, phone
),

first_call as (
    select
        p.client,
        p.phone,
        k.call_id,
        k.click_id,
        k.tracking_campaign_id
    from people as p
    inner join {{ ref('slv_calls') }} as k
        on
            p.phone = k.caller_phone
            and k.started_at between p.first_at - interval 1 day and p.first_at + interval 1 day
    qualify row_number() over (partition by p.client, p.phone order by k.started_at, k.call_id) = 1
)

select
    p.client || ':' || p.phone as lead_key,
    p.client,
    p.phone,
    p.email,
    p.first_at,
    p.first_at::date as lead_day,
    case when p.first_source = 'web_form' then 'form' else 'call' end as came_by,
    p.crm_records,
    p.crm_click_id,
    k.call_id,
    k.click_id as call_click_id,
    coalesce(cc.campaign_id, kc.campaign_id, k.tracking_campaign_id) as campaign_id,
    case
        when cc.campaign_id is not null then 'crm_click_id'
        when kc.campaign_id is not null then 'call_click_id'
        when k.tracking_campaign_id is not null then 'tracking_number'
        else 'none'
    end as attributed_by,
    case p.status_rank when 3 then 'demo_done' when 2 then 'issued' when 1 then 'rejected' else 'new' end
        as status,
    p.status_rank >= 2 as issued,
    p.status_rank = 3 as demo
from people as p
left join first_call as k on p.client = k.client and p.phone = k.phone
left join {{ ref('slv_ad_clicks') }} as cc on p.crm_click_id = cc.click_id
left join {{ ref('slv_ad_clicks') }} as kc on k.click_id = kc.click_id
