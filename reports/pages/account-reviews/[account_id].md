---
title: Account review
---

```sql acct
select * from ridgeline.account_review
where account_id = '${params.account_id}'
```

```sql months
select strftime(month, '%Y-%m') as month_label, month, mrr, net_new_mrr, tickets, measurement_orders,
       redo_orders, leads, closed_leads, won_leads
from ridgeline.account_review_monthly
where account_id = '${params.account_id}'
order by month
```

```sql totals
select sum(tickets) as tickets, sum(measurement_orders) as orders, sum(redo_orders) as redos,
       sum(leads) as leads,
       sum(won_leads) / nullif(sum(closed_leads), 0) as close_rate
from ridgeline.account_review_monthly
where account_id = '${params.account_id}'
```

# <Value data={acct} column=company_name/>

<Value data={acct} column=region/> · crew of <Value data={acct} column=crew_size/> ·
<Value data={acct} column=plan/> plan · customer since <Value data={acct} column=signup_date fmt=mmm-yyyy/> ·
review as of <Value data={acct} column=as_of fmt=longdate/> (simulated data)

<BigValue data={acct} value=mrr title="MRR now" fmt=usd0/>
<BigValue data={acct} value=health_score title="Health score"/>
<BigValue data={totals} value=leads title="Leads, 12 months" fmt=num0/>
<BigValue data={totals} value=close_rate title="Lead close rate" fmt=pct0/>
<BigValue data={totals} value=redos title="Measurement redos" fmt=num0/>
<BigValue data={totals} value=tickets title="Support tickets" fmt=num0/>

## Talking points

<Value data={acct} column=talking_points/>

## MRR, last 12 complete months

<LineChart data={months} x=month y=mrr yFmt=usd0 colorPalette={['#C2410C']}/>

## Their homeowner leads

<BarChart data={months} x=month y={['won_leads', 'closed_leads']} type=grouped title="Closed and won leads by month" colorPalette={['#C2410C', '#FDBA74']}/>

## Product use and support

Last 30 days: <Value data={acct} column=logins_30d/> logins and <Value data={acct} column=proposals_30d/> proposals
sent. Last 90 days: <Value data={acct} column=tickets_90d/> tickets and <Value data={acct} column=redo_90d/> redo
requests. These feed the health score (band: <Value data={acct} column=risk_band/>), defined on the
[Retention page](/retention).

<DataTable data={months} rows=12>
  <Column id=month_label title="Month"/>
  <Column id=mrr title="MRR" fmt=usd0/>
  <Column id=net_new_mrr title="MRR change" fmt=usd0/>
  <Column id=leads title="Leads"/>
  <Column id=won_leads title="Won"/>
  <Column id=measurement_orders title="Measurements"/>
  <Column id=redo_orders title="Redos"/>
  <Column id=tickets title="Tickets"/>
</DataTable>

[All account reviews](/account-reviews)
