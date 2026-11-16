-- A renewed term's next term starts the day it ends: no gap, no overlap.
select t.term_id
from {{ ref('stg_book__terms') }} as t
inner join {{ ref('stg_book__terms') }} as n
    on t.policy_id = n.policy_id and n.term_number = t.term_number + 1
where n.start_date != t.end_date
