-- Ontario's public ICU file, one row per day, with the two things a data test should notice: more patients than
-- beds, and a day whose adult patient count is far (more than 25%) from the median of the week around it.
with d as (
    select
        *,
        median(total_adult_icu_patients) over (
            order by census_date rows between 3 preceding and 3 following
        ) as adult_patients_week_median
    from {{ ref('stg_public__ontario_icu_beds') }}
)

select
    *,
    total_adult_icu_patients > total_adult_icu_beds or total_ped_icu_patients > total_ped_icu_beds as over_capacity,
    abs(total_adult_icu_patients - adult_patients_week_median) > 0.25 * adult_patients_week_median
        as adult_patients_outlier
from d
