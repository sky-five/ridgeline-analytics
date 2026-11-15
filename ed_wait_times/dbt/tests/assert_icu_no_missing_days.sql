-- The public ICU file has one row for every day from its first to its last.
select count(*) as days, date_diff('day', min(census_date), max(census_date)) + 1 as span
from {{ ref('stg_public__ontario_icu_beds') }}
having count(*) != date_diff('day', min(census_date), max(census_date)) + 1
