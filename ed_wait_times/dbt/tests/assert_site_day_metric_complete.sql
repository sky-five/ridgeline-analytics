-- Every site has every day and every metric exactly once.
with expected as (
    select
        (select count(*) from {{ ref('dim_sites') }})
        * (select count(distinct census_date) from {{ ref('stg_ed__bed_census') }})
        * 8 as n
)

select 'rows' as problem, (select count(*) from {{ ref('fct_site_day_metric') }}) as n
from expected
where (select count(*) from {{ ref('fct_site_day_metric') }}) != expected.n
union all
select 'duplicate key', count(*)
from {{ ref('fct_site_day_metric') }}
group by site_id, day, metric
having count(*) > 1
