-- When an account reconciles to the ledger today and yesterday, market P&L, deposits and interest explain
-- the whole change in its equity.
with recon as (
    select
        as_of_date,
        account_id,
        is_break or lag(is_break) over (partition by account_id order by as_of_date) as touched
    from {{ ref('reconciliation_account_day') }}
)

select p.as_of_date, p.account_id, p.unexplained
from {{ ref('fct_account_pnl_day') }} as p
inner join recon as r on p.as_of_date = r.as_of_date and p.account_id = r.account_id
where not r.touched and abs(p.unexplained) > 0.05
