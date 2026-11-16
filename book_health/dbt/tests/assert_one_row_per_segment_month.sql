select month_start, province, product, channel
from {{ ref('fct_segment_month') }}
group by all
having count(*) > 1
