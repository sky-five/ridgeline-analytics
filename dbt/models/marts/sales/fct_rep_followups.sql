-- Did sales call the best free accounts quickly once they became eligible (14 days after signup)?
with top_accounts as (
    select
        account_id,
        split,
        is_paid_60d,
        {{ dbt.dateadd('day', 14, 'signup_at') }} as became_eligible_at
    from {{ ref('fct_pqa_scores') }}
    where decile = 10 and split <> 'train'
),

-- only calls made once the account was eligible count as a follow-up
eligible_calls as (
    select
        t.account_id,
        c.called_at,
        c.rep,
        row_number() over (partition by t.account_id order by c.called_at) as call_rank
    from top_accounts as t
    inner join {{ ref('stg_crm__calls') }} as c
        on t.account_id = c.account_id and t.became_eligible_at <= c.called_at
)

select
    t.account_id,
    cast(t.became_eligible_at as timestamp) as became_eligible_at,
    c.called_at as first_call_at,
    c.rep,
    coalesce(c.called_at <= {{ dbt.dateadd('day', 3, 't.became_eligible_at') }}, false) as called_within_3d,
    -- the 60-day outcome is only known for accounts old enough (the test split)
    case when t.split = 'test' then coalesce(t.is_paid_60d, false) end as converted_60d
from top_accounts as t
left join eligible_calls as c on t.account_id = c.account_id and c.call_rank = 1
