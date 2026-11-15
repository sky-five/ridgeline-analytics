-- Program groups from StatCan's STEM and BHASE grouping of CIP Canada 2021 (the leaf level of table 37-10-0163).
select program_code, program_name, program_group
from (values
    ('a.1', 'Science and science technology', 'STEM'),
    ('a.2', 'Engineering and engineering technology', 'STEM'),
    ('a.3', 'Mathematics and computer and information sciences', 'STEM'),
    ('b.1', 'Business and administration', 'BHASE'),
    ('b.2', 'Arts and humanities', 'BHASE'),
    ('b.3', 'Social and behavioural sciences', 'BHASE'),
    ('b.4', 'Legal professions and studies', 'BHASE'),
    ('b.5', 'Health care', 'BHASE'),
    ('b.6', 'Education and teaching', 'BHASE'),
    ('b.7', 'Trades, services, natural resources and conservation', 'BHASE'),
    ('u', 'Unclassified, instructional program', 'Unclassified')
) as t (program_code, program_name, program_group)
