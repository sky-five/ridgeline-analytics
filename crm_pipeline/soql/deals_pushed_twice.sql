select opportunity_id, count(*) as pushes
from stg_crm__opportunity_history
where change_type = 'close_date_push'
group by opportunity_id
having count(*) >= 2
order by pushes desc, opportunity_id
