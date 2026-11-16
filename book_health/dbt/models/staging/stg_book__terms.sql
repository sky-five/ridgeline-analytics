-- One row per policy term. outcome: renewed (the policy has a next term), lapsed (the term ended on or before the
-- as-of date with no next term) or not_due (it ends after the as-of date). renewal_offer_change is the premium
-- change offered for the next term, whether the customer took it or not.
with terms as (
    select
        t.term_id,
        t.policy_id,
        p.province,
        p.product,
        p.channel,
        t.term_number,
        t.start_date::date as start_date,
        t.end_date::date as end_date,
        t.written_premium::decimal(18, 2) as written_premium,
        t.rate_change,
        t.renewal_offer_change
    from {{ source('raw_book', 'terms') }} as t
    inner join {{ source('raw_book', 'policies') }} as p using (policy_id)
)

select
    terms.*,
    date_trunc('month', terms.end_date)::date as renewal_month,
    case
        when terms.end_date > date '{{ var("as_of") }}' then 'not_due'
        when nxt.term_id is not null then 'renewed'
        else 'lapsed'
    end as outcome
from terms
left join terms as nxt
    on terms.policy_id = nxt.policy_id and nxt.term_number = terms.term_number + 1
