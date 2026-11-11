---
title: Opportunities
---

Paying accounts worth a call this month: their measurement orders are falling, or the share of homeowner leads
they win has dipped. Each account's last <Value data={opps_meta} column=window/> complete months
(<Value data={opps_meta} column=after_start fmt=mmm-yyyy/> to <Value data={opps_meta} column=last_month fmt=mmm-yyyy/>)
are compared with the <Value data={opps_meta} column=window/> months before, from the governed metrics
`measurement_orders`, `won_leads` and `closed_leads` grouped by account. Data is simulated.

- **Orders falling**: at least 6 measurement orders in the earlier months, and 40% or more fewer since.
- **Close rate dip**: at least 8 closed leads in each window, and won / closed down 15 points or more.

```sql opps_meta
select 3 as window, min(after_start) as after_start, min(last_month) as last_month, count(*) as n,
       sum(mrr) as mrr, sum(case when orders_falling then 1 else 0 end) as n_orders,
       sum(case when close_rate_dip then 1 else 0 end) as n_rate
from ridgeline.account_opportunities
```

```sql opps
select rank, account_id, company_name, region, plan, mrr, health_score, risk_band,
       case when orders_falling and close_rate_dip then 'Both'
            when orders_falling then 'Orders falling' else 'Close rate dip' end as flag,
       measurement_orders_before, measurement_orders_after, orders_change,
       close_rate_before, close_rate_after, reason, review_link
from ridgeline.account_opportunities
order by rank
```

<BigValue data={opps_meta} value=n title="Accounts flagged" fmt=num0/>
<BigValue data={opps_meta} value=mrr title="Their MRR" fmt=usd0k/>
<BigValue data={opps_meta} value=n_orders title="Orders falling" fmt=num0/>
<BigValue data={opps_meta} value=n_rate title="Close rate dip" fmt=num0/>

Accounts with both flags come first, then by MRR. Rows with a link open that account's review page.

<DataTable data={opps} link=review_link rows=25 search=true>
  <Column id=rank title="#"/>
  <Column id=company_name title="Account"/>
  <Column id=flag/>
  <Column id=mrr title="MRR" fmt=usd0/>
  <Column id=health_score title="Health"/>
  <Column id=reason title="Why" wrap=true/>
</DataTable>

The rule is deliberately simple and the thresholds are fixed in
[account_reviews/opportunities.py](https://github.com/sky-five/ridgeline-analytics/blob/main/account_reviews/opportunities.py).
A flag says where to look, not why it happened.
