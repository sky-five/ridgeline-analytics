-- One row per margin call: a run of weekdays an account spent below its requirement. How it ended: a
-- deposit, a liquidation (the loan fell on the day it was cured), the market (prices recovered) or still open.
-- A call that starts on an account-day that does not reconcile to the ledger may not be real.
with days as (
    select
        *,
        row_number() over (partition by account_id order by as_of_date)
        - row_number() over (partition by account_id, in_call order by as_of_date) as run_id,
        lead(as_of_date) over (partition by account_id order by as_of_date) as next_date,
        lead(loan) over (partition by account_id order by as_of_date) as next_loan
    from {{ ref('fct_account_day') }}
),

calls as (
    select
        account_id,
        min(as_of_date) as call_date,
        max(as_of_date) as last_day_in_call,
        count(*) as weekdays_in_call,
        arg_min(deficit, as_of_date) as deficit_at_call,
        max(deficit) as max_deficit,
        arg_max(top_symbol, as_of_date) as top_symbol,
        bool_or(is_concentrated) as was_concentrated,
        arg_max(next_date, as_of_date) as cured_date,
        arg_max(loan, as_of_date) as loan_last_day,
        arg_max(next_loan, as_of_date) as loan_cured_day
    from days
    where in_call
    group by account_id, run_id
),

deposits as (
    select account_id, as_of_date, sum(amount) as amount
    from {{ source('raw_margin', 'cash_activity') }}
    where kind = 'deposit'
    group by account_id, as_of_date
)

select
    c.account_id,
    c.call_date,
    c.last_day_in_call,
    c.cured_date,
    c.weekdays_in_call,
    c.deficit_at_call,
    c.max_deficit,
    c.top_symbol,
    c.was_concentrated,
    case
        when c.cured_date is null then 'open'
        when d.amount is not null then 'deposit'
        when c.loan_cured_day < c.loan_last_day * 0.99 then 'liquidated'
        else 'market'
    end as resolution,
    coalesce(r.is_break, false) as starts_on_break
from calls as c
left join deposits as d on c.account_id = d.account_id and c.cured_date = d.as_of_date
left join {{ ref('reconciliation_account_day') }} as r
    on c.account_id = r.account_id and c.call_date = r.as_of_date
