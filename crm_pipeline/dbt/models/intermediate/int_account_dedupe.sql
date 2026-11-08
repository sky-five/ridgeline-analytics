-- Maps every account record to the earliest record of the same company.
-- Rule 1: same website. Rule 2 (no website on the record): same name key and billing state.
-- Name alone is not enough: different companies share names like 'Golden Crest Roofing Co' in other states.
with accounts as (
    select * from {{ ref('stg_crm__accounts') }}
),

ranked as (
    select
        account_id,
        website,
        first_value(account_id) over (
            partition by coalesce(website, 'no-site:' || account_id) order by created_at, account_id
        ) as first_by_website,
        first_value(account_id) over (
            partition by name_key, billing_state order by created_at, account_id
        ) as first_by_name_state
    from accounts
)

select
    account_id,
    case
        when first_by_website != account_id then first_by_website
        when website is null and first_by_name_state != account_id then first_by_name_state
        else account_id
    end as canonical_account_id,
    case
        when first_by_website != account_id then 'website'
        when website is null and first_by_name_state != account_id then 'name_and_state'
    end as matched_on
from ranked
