-- IRCC's own all-Canada row per month and study level. It includes permits with no province stated, so it is
-- the series to forecast for the country, not the provinces added up.
select permit_month, study_level, permits
from {{ ref('stg_ircc__study_permits') }}
where region_code = 'CA'
