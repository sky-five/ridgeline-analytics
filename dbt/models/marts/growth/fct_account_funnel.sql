with accounts as (
    select * from {{ ref('dim_accounts') }}
),

early as (
    select * from {{ ref('int_account_first14d') }}
),

milestones as (
    select * from {{ ref('int_account_milestones') }}
),

joined as (
    select
        a.account_id,
        a.signup_at,
        a.channel,
        a.region,
        a.crew_size,
        a.first_paid_at,
        e.logins_14d,
        e.measurements_14d,
        e.proposals_14d,
        e.signed_14d,
        e.active_days_14d,
        e.proposal_wk1,
        m.first_measurement_at,
        m.first_proposal_at,
        m.first_signed_at,
        {{ dbt.dateadd('day', 60, 'a.signup_at') }} as day_60_at
    from accounts as a
    left join early as e on a.account_id = e.account_id
    left join milestones as m on a.account_id = m.account_id
)

select
    account_id,
    signup_at,
    cast({{ dbt.date_trunc('month', 'signup_at') }} as date) as signup_month,
    channel,
    region,
    crew_size,
    cast(coalesce(logins_14d, 0) as {{ dbt.type_bigint() }}) as logins_14d,
    cast(coalesce(measurements_14d, 0) as {{ dbt.type_bigint() }}) as measurements_14d,
    cast(coalesce(proposals_14d, 0) as {{ dbt.type_bigint() }}) as proposals_14d,
    cast(coalesce(signed_14d, 0) as {{ dbt.type_bigint() }}) as signed_14d,
    cast(coalesce(active_days_14d, 0) as {{ dbt.type_bigint() }}) as active_days_14d,
    coalesce(proposal_wk1, false) as proposal_wk1,
    first_measurement_at,
    first_proposal_at,
    first_signed_at,
    first_paid_at,
    coalesce(proposals_14d, 0) > 0 as is_activated,
    coalesce(first_measurement_at < day_60_at, false) as measured_60d,
    coalesce(first_proposal_at < day_60_at, false) as proposed_60d,
    coalesce(first_signed_at < day_60_at, false) as signed_60d,
    coalesce(first_paid_at < day_60_at, false) as is_paid_60d,
    cast(signup_at as date) <= {{ dbt.dateadd('day', -60, as_of_date()) }} as is_mature
from joined
