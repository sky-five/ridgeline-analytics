-- For a borrower, equity below requirement and collateral coverage below 1 are the same statement.
select as_of_date, account_id
from {{ ref('fct_account_day') }}
where loan > 0 and abs(excess) > 0.01 and in_call != (collateral_coverage < 1)
