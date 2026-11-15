-- The public file with its columns kept as published, plus occupancy as patients over beds.
select
    cast(date as date) as census_date,
    adult_icu_crci_patients,
    adult_icu_non_crci_patients,
    total_adult_icu_patients,
    available_adult_icu_beds,
    total_adult_icu_beds,
    ped_icu_crci_patients,
    ped_icu_non_crci_patients,
    total_ped_icu_patients,
    available_ped_icu_beds,
    total_ped_icu_beds,
    total_adult_icu_patients / total_adult_icu_beds as adult_occupancy_rate,
    total_ped_icu_patients / total_ped_icu_beds as ped_occupancy_rate
from {{ source('raw_public', 'ontario_icu_beds') }}
