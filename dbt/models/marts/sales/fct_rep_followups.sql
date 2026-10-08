-- Did sales call the best free accounts quickly once they became eligible?
with top_accounts as (
    select
        account_id,
        is_paid_60d,
        {{ dbt.dateadd('day', 14, 'signup_at') }} as became_eligible_at
    from {{ ref('fct_pqa_scores') }}
    where decile = 10 and split <> 'train'
),

first_calls as (
    select
        account_id,
        min(called_at) as first_call_at,
        min(rep) as rep
    from {{ ref('stg_crm__calls') }}
    group by account_id
)

select
    t.account_id,
    cast(t.became_eligible_at as timestamp) as became_eligible_at,
    c.first_call_at,
    c.rep,
    coalesce(c.first_call_at <= {{ dbt.dateadd('day', 3, 't.became_eligible_at') }}, false) as called_within_3d,
    coalesce(t.is_paid_60d, false) as converted_60d
from top_accounts as t
left join first_calls as c on t.account_id = c.account_id
