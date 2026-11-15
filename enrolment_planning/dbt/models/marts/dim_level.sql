-- ISCED 2011 levels. Tertiary is ISCED 5 to 8.
select isced_code, level_name, isced_code in ('5', '6', '7', '8') as is_tertiary
from (values
    ('3', 'Upper secondary education'),
    ('4', 'Post-secondary non-tertiary education'),
    ('5', 'Short-cycle tertiary education'),
    ('6', 'Bachelor''s or equivalent'),
    ('7', 'Master''s or equivalent'),
    ('8', 'Doctoral or equivalent'),
    ('9', 'Not in ISCED')
) as t (isced_code, level_name)
