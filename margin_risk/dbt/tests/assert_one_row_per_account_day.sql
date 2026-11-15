-- The risk mart has one row per account and day, and so does the reconciliation.
select as_of_date, account_id from {{ ref('fct_account_day') }}
group by as_of_date, account_id having count(*) > 1
union all
select as_of_date, account_id from {{ ref('reconciliation_account_day') }}
group by as_of_date, account_id having count(*) > 1
