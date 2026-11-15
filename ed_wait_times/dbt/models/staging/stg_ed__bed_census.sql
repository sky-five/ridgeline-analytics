select
    site_id,
    cast(census_date as date) as census_date,
    staffed_beds,
    occupied_beds,
    occupied_beds / staffed_beds as occupancy_rate
from {{ source('raw_ed', 'bed_census') }}
