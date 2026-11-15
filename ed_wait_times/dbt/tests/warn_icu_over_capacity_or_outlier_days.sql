-- Days in the public file with more ICU patients than beds or a patient count far from its week. They are real rows
-- as published, so this warns and lists them (results/summary.json) instead of failing the build.
{{ config(severity='warn') }}
select census_date, total_adult_icu_patients, total_adult_icu_beds, total_ped_icu_patients, total_ped_icu_beds
from {{ ref('icu_province_day') }}
where over_capacity or adult_patients_outlier
