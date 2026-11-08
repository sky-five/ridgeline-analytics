-- One row per real company: duplicate records folded into the earliest one.
with dedupe as (
    select * from {{ ref('int_account_dedupe') }}
),

records as (
    select canonical_account_id, count(*) as crm_records
    from dedupe
    group by canonical_account_id
),

deals as (
    select
        account_id,
        count(*) as opportunities,
        sum(case when is_won then amount_usd else 0 end) as won_usd
    from {{ ref('fct_opportunities') }}
    group by account_id
)

select
    a.account_id,
    a.account_name,
    a.website,
    a.billing_state,
    a.segment,
    a.employee_count,
    a.created_at,
    r.crm_records,
    coalesce(d.opportunities, 0) as opportunities,
    coalesce(d.won_usd, 0) as won_usd
from {{ ref('stg_crm__accounts') }} as a
inner join records as r on a.account_id = r.canonical_account_id
left join deals as d on a.account_id = d.account_id
