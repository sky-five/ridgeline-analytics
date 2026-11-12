-- Every month that has closed by the as-of date, from the first billing or CRM activity.
with bounds as (
    select least(
        (select min(month_start) from {{ ref('stg_billing__subscription_changes') }}),
        (select min(month_start) from {{ ref('stg_crm__won_deals') }})
    ) as first_month
)

select
    cast(m as date) as month_start,
    cast(m + interval 1 month - interval 1 day as date) as month_last_day
from bounds, generate_series(first_month, date '{{ var("as_of_date") }}', interval 1 month) as t (m)
where m + interval 1 month - interval 1 day <= date '{{ var("as_of_date") }}'
