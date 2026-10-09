---
title: Executive scorecard
---

<Alert status="info">
Ridgeline is a fictional roofing-software company. All data is synthetic. Every number on this site comes from the
governed metric definitions in the <a href="/metrics">semantic layer</a>.
</Alert>

```sql weekly
with w as (
    select
        week,
        mrr,
        paying_accounts,
        net_new_mrr,
        signups,
        lead_close_rate,
        tickets,
        mrr / lag(mrr) over (order by week) - 1 as mrr_change,
        signups / lag(signups) over (order by week) - 1 as signups_change,
        tickets / lag(tickets) over (order by week) - 1 as tickets_change
    from ridgeline.kpi_weekly
)
-- the latest week is still in progress, so the scorecard shows complete weeks only
select * from w
where week < (select max(week) from ridgeline.kpi_weekly)
order by week desc
limit 26
```

```sql latest_week
select strftime(week, '%b %d, %Y') as week_label from ${weekly} limit 1
```

## Last complete week: <Value data={latest_week} column=week_label />

<BigValue data={weekly} value=mrr title="MRR" fmt=usd0k sparkline=week comparison=mrr_change comparisonFmt=pct1 comparisonTitle="vs prior week"/>
<BigValue data={weekly} value=paying_accounts title="Paying accounts" sparkline=week/>
<BigValue data={weekly} value=signups title="Signups" sparkline=week comparison=signups_change comparisonFmt=pct0 comparisonTitle="vs prior week"/>
<BigValue data={weekly} value=net_new_mrr title="Net new MRR" fmt=usd0 sparkline=week/>
<BigValue data={weekly} value=tickets title="Support tickets" sparkline=week comparison=tickets_change comparisonFmt=pct0 comparisonTitle="vs prior week" downIsGood=true/>

## MRR against target

```sql mrr_vs_target
select k.month, k.mrr as actual, t.target
from ridgeline.kpi_monthly k
left join ridgeline.targets t on t.month = k.month and t.metric = 'mrr'
where k.month >= '2025-01-01'
order by k.month
```

<LineChart data={mrr_vs_target} x=month y={['actual', 'target']} yFmt=usd0k title="Month-end MRR vs target" colorPalette={['#C2410C', '#9CA3AF']}/>

## Where MRR moved

```sql movements
select month, new_mrr as "New", expansion_mrr as "Expansion", churned_mrr as "Churned"
from ridgeline.kpi_monthly
where month >= '2025-01-01'
order by month
```

<BarChart data={movements} x=month y={['New', 'Expansion', 'Churned']} yFmt=usd0k title="MRR movements by month" colorPalette={['#C2410C', '#F59E0B', '#6B7280']}/>

```sql headline
select * from ridgeline.headline
```

## What to know this week

- **Retention is the biggest lever.** A paid cohort keeps <Value data={headline} column=nrr_12m fmt=pct0/> of its MRR after 12 months. Churn is high for small crews, and measurement redos (<Value data={headline} column=measurement_redo_rate fmt=pct1/> of reports) push it up.
- **Activation predicts revenue.** Free accounts that send a proposal in their first 14 days convert about 8× as often. See [Acquisition](/acquisition).
- **Sales has a ranked call list** of free accounts most likely to pay. See [Ready for sales](/sales).
