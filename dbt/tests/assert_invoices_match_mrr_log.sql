-- Reconciliation: every subscription invoice must equal the account's MRR in the movement log
-- at the moment it was issued. Returns the invoices that don't match.
with invoices as (
    select invoice_id, account_id, issued_at, amount_usd
    from {{ ref('stg_app_db__invoices') }}
    where line_type = 'subscription'
),

matched as (
    select
        i.invoice_id,
        i.amount_usd,
        m.mrr_after,
        row_number() over (partition by i.invoice_id order by m.changed_at desc) as rn
    from invoices as i
    left join {{ ref('fct_mrr_movements') }} as m
        on i.account_id = m.account_id and m.changed_at <= i.issued_at
)

select invoice_id, amount_usd, mrr_after
from matched
where rn = 1 and (mrr_after is null or abs(amount_usd - mrr_after) > 0.01)
