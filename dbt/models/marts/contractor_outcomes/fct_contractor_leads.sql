with leads as (
    select
        *,
        {{ dbt.datediff('created_at', 'first_contact_at', 'minute') }} as speed_to_lead_min  -- noqa: LT05
    from {{ ref('stg_contractor_ops__leads') }}
)

select
    lead_id,
    account_id,
    lead_source,
    created_at,
    cast({{ dbt.date_trunc('month', 'created_at') }} as date) as created_month,
    first_contact_at,
    inspection_at,
    proposal_sent_at,
    closed_at,
    outcome,
    case
        when outcome = 'won' then 'won'
        when outcome like 'lost_%' then 'lost'
        when outcome in ('unqualified', 'no_response') then outcome
        else 'open'
    end as outcome_group,
    cast(proposal_value_usd as {{ dbt.type_numeric() }}) as proposal_value_usd,
    cast(speed_to_lead_min as {{ dbt.type_bigint() }}) as speed_to_lead_min,
    case
        when speed_to_lead_min is null then 'missing'
        when speed_to_lead_min < 5 then 'lt_5m'
        when speed_to_lead_min < 60 then '5_60m'
        when speed_to_lead_min < 1440 then '1_24h'
        else 'gt_1d'
    end as speed_bucket,
    first_contact_at is null and outcome <> 'no_response' as missing_contact_ts,
    inspection_at is null and proposal_sent_at is not null as missing_inspection_ts
from leads
