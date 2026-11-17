-- Each week, at least min_click_id_match of the click ids on CRM records match a click the ad platforms sent
-- (a change in how the form stores the id would quietly turn paid leads into unattributed ones).
select
    date_trunc('week', r.created_at) as week,
    count(*) as crm_click_ids,
    count(k.click_id) as matched,
    round(count(k.click_id) / count(*), 4) as match_rate
from {{ ref('slv_crm_records') }} as r
left join {{ ref('slv_ad_clicks') }} as k on r.click_id = k.click_id
where r.click_id is not null
group by all
having count(k.click_id) / count(*) < {{ var('min_click_id_match') }}
