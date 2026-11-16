-- The province months add up to the segment months, and the renewals counted equal the terms that came due.
with seg as (
    select sum(renewals_due) as due, sum(renewed) as renewed, sum(incurred) as incurred
    from {{ ref('fct_segment_month') }}
),

prov as (
    select sum(renewals_due) as due, sum(renewed) as renewed, sum(incurred) as incurred
    from {{ ref('province_month') }}
),

terms as (
    select count(*) filter (where outcome != 'not_due') as due, count(*) filter (where outcome = 'renewed') as renewed
    from {{ ref('stg_book__terms') }}
    where end_date >= date '{{ var("first_month") }}'
)

select * from seg, prov, terms
where seg.due != prov.due or seg.renewed != prov.renewed or seg.incurred != prov.incurred
    or seg.due != terms.due or seg.renewed != terms.renewed
