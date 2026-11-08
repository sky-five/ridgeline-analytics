-- CloseDate = LAST_QUARTER, with the as-of date 2026-06-30 (so 2026-01-01 to 2026-03-31).
-- This reads the recorded close date, as the object query would; fct_opportunities has the corrected one.
select lead_source, count(*) as deals, sum(amount_usd) as won
from stg_crm__opportunities
where is_won and close_date between date '2026-01-01' and date '2026-03-31'
group by lead_source
order by won desc
