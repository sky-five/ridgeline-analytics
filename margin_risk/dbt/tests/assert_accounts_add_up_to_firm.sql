-- The firm summary is the sum of its accounts.
select f.as_of_date
from {{ ref('daily_firm_summary') }} as f
inner join (
    select as_of_date, sum(market_value) as mv, sum(loan) as loan, count(*) filter (where in_call) as calls
    from {{ ref('fct_account_day') }}
    group by as_of_date
) as a on f.as_of_date = a.as_of_date
where abs(f.market_value - a.mv) > 0.01 or abs(f.loan - a.loan) > 0.01 or f.accounts_in_call != a.calls
