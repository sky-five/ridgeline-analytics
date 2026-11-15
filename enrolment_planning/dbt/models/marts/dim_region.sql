-- Provinces and the territories as one region (StatCan groups them; IRCC rows for the three are added up).
select region_code, region_name
from (values
    ('NL', 'Newfoundland and Labrador'), ('PE', 'Prince Edward Island'), ('NS', 'Nova Scotia'),
    ('NB', 'New Brunswick'), ('QC', 'Quebec'), ('ON', 'Ontario'), ('MB', 'Manitoba'),
    ('SK', 'Saskatchewan'), ('AB', 'Alberta'), ('BC', 'British Columbia'), ('TR', 'Territories')
) as t (region_code, region_name)
