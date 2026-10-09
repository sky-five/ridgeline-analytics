---
title: Acquisition funnel
---

How free signups turn into paying contractors, by channel. "Free to paid" counts only signups at least 60 days old,
so recent cohorts don't drag the rate down.

```sql channels
select channel, signups, activation_rate, free_to_paid_60d
from ridgeline.channel_funnel
order by free_to_paid_60d desc
```

<BarChart data={channels} x=channel y=free_to_paid_60d yFmt=pct0 swapXY=true title="Free to paid within 60 days, by channel" colorPalette={['#C2410C']}/>

<DataTable data={channels} rows=all>
  <Column id=channel title="Channel"/>
  <Column id=signups title="Signups"/>
  <Column id=activation_rate title="Activation" fmt=pct1 contentType=bar barColor="#FDBA74"/>
  <Column id=free_to_paid_60d title="Free → paid (60d)" fmt=pct1 contentType=bar barColor="#FDBA74"/>
</DataTable>

## Cost to acquire a paying customer

Paid channels only. CAC = spend ÷ paid conversions from that month's signups.

```sql cac
select month, channel, cac, ad_spend, paid_conversions
from ridgeline.channel_cac_monthly
where ad_spend > 0 and paid_conversions > 0 and month >= '2025-01-01'
  and month < (select max(month) - interval 2 month from ridgeline.channel_cac_monthly)
order by month
```

<LineChart data={cac} x=month y=cac series=channel yFmt=usd0 title="CAC by paid channel (cohorts with a known outcome)"/>

## Signups against target

```sql signups
select k.month, k.signups as actual, t.target
from ridgeline.kpi_monthly k
left join ridgeline.targets t on t.month = k.month and t.metric = 'signups'
where k.month >= '2025-01-01'
order by k.month
```

<LineChart data={signups} x=month y={['actual', 'target']} title="Signups per month vs target" colorPalette={['#C2410C', '#9CA3AF']}/>

The storm season (April–August) brings more signups every year, so the targets follow it.
