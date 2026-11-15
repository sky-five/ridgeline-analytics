-- Status of student in Canada. Permanent residents count as Canadian students in StatCan's grouping.
select status_code, status_name
from (values
    ('CAN', 'Canadian students'),
    ('INT', 'International students'),
    ('NR', 'Not reported')
) as t (status_code, status_name)
