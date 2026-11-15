-- In the public ICU file, COVID and non-COVID patients add up to all patients, and patients plus available beds
-- add up to beds, for adults and children, on every day.
select census_date
from {{ ref('stg_public__ontario_icu_beds') }}
where adult_icu_crci_patients + adult_icu_non_crci_patients != total_adult_icu_patients
    or total_adult_icu_patients + available_adult_icu_beds != total_adult_icu_beds
    or ped_icu_crci_patients + ped_icu_non_crci_patients != total_ped_icu_patients
    or total_ped_icu_patients + available_ped_icu_beds != total_ped_icu_beds
