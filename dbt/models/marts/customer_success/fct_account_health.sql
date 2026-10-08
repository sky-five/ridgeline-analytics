-- Rule-based health score for paying accounts. Rules are documented in _customer_success_models.yml.
with scored as (
    select
        a.account_id,
        a.company_name,
        a.current_plan,
        a.current_mrr,
        act.logins_30d,
        act.proposals_30d,
        act.tickets_90d,
        act.redo_90d,
        100
        - case when act.logins_30d < 4 then 30 else 0 end
        - case when act.proposals_30d = 0 then 20 else 0 end
        - case when act.redo_90d > 0 then 20 else 0 end
        - 10 * greatest(act.tickets_90d - 2, 0) as raw_score
    from {{ ref('dim_accounts') }} as a
    inner join {{ ref('int_account_activity') }} as act on a.account_id = act.account_id
    where a.is_paying
)

select
    account_id,
    company_name,
    current_plan,
    cast(current_mrr as {{ dbt.type_numeric() }}) as mrr,
    cast(logins_30d as {{ dbt.type_bigint() }}) as logins_30d,
    cast(proposals_30d as {{ dbt.type_bigint() }}) as proposals_30d,
    cast(tickets_90d as {{ dbt.type_bigint() }}) as tickets_90d,
    cast(redo_90d as {{ dbt.type_bigint() }}) as redo_90d,
    cast(greatest(raw_score, 0) as {{ dbt.type_int() }}) as health_score,
    case
        when greatest(raw_score, 0) < 40 then 'at_risk'
        when greatest(raw_score, 0) < 70 then 'watch'
        else 'healthy'
    end as risk_band
from scored
