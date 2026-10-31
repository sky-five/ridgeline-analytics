---
title: Retention and expansion
---

Who stays, who grows, and why the rest leave. Contractors are small businesses, so logo churn is the main lever:
the 12-month NRR below is the governed `nrr_12m` metric, the same one the AI analyst uses.

```sql headline
select nrr_12m from ridgeline.headline
```

```sql bands
select
    sum(accounts) filter (where risk_band = 'healthy') as healthy,
    sum(accounts) filter (where risk_band = 'watch') as watch,
    sum(accounts) filter (where risk_band = 'at_risk') as at_risk,
    sum(mrr) filter (where risk_band <> 'healthy') as mrr_needing_attention
from ridgeline.health_bands
```

<BigValue data={headline} value=nrr_12m title="12-month NRR" fmt=pct0/>
<BigValue data={bands} value=healthy title="Healthy accounts"/>
<BigValue data={bands} value=watch title="On watch"/>
<BigValue data={bands} value=at_risk title="At risk"/>
<BigValue data={bands} value=mrr_needing_attention title="MRR on watch or at risk" fmt=usd0k/>

## Retention by signup cohort

Share of each month's new paying accounts still paying N months later. Read across a row to follow one cohort;
read down a column to see whether newer cohorts hold on better than older ones.

```sql cohorts
select strftime(cohort_month, '%Y-%m') as cohort, months_since_start, logo_retention
from ridgeline.cohort_retention
where cohort_month >= '2025-01-01'
order by cohort_month, months_since_start
```

<Heatmap data={cohorts} x=months_since_start y=cohort value=logo_retention valueFmt=pct0 colorScale={['#FFF7ED', '#C2410C']} title="Logo retention by cohort (months since first payment)"/>

```sql curve
select months_since_start, logo_retention, nrr
from ridgeline.retention_curve
where cohorts >= 6
```

<LineChart data={curve} x=months_since_start y={['logo_retention', 'nrr']} yFmt=pct0 xAxisTitle="Months since first payment" title="All cohorts: accounts kept vs revenue kept" colorPalette={['#C2410C', '#9CA3AF']}/>

When the revenue line sits above the accounts line, the customers who stay are upgrading or adding add-ons faster
than the leavers take revenue away.

## Why accounts leave

```sql reasons
select replace(cancel_reason, '_', ' ') as reason, churned_accounts
from ridgeline.churn_reasons
```

<BarChart data={reasons} x=reason y=churned_accounts swapXY=true title="Cancel reasons, last 12 months" colorPalette={['#C2410C']}/>

```sql themes
select month, replace(churn_theme, '_', ' ') as theme, tickets
from ridgeline.ticket_themes_monthly
where month < (select max(month) from ridgeline.ticket_themes_monthly)
```

<AreaChart data={themes} x=month y=tickets series=theme title="Support tickets from paying accounts, by theme"/>

Measurement accuracy leads both charts: redone roof reports drive tickets first and cancellations later.
Ticket themes come from a classifier trained on 300 hand-labelled tickets (see Data health).

## Add-ons

```sql addons
select replace(addon, '_', ' ') as addon, accounts, share_of_paying
from ridgeline.addon_adoption
```

<DataTable data={addons}>
  <Column id=addon title="Add-on"/>
  <Column id=accounts title="Paying accounts"/>
  <Column id=share_of_paying title="Share of paying" fmt=pct1 contentType=bar barColor="#FDBA74"/>
</DataTable>

## Accounts to call this week

Lowest health score first. The score is rule-based (logins, proposals sent, tickets and report redos), so every
point can be explained to the account manager.

```sql risk
select company_name, current_plan, mrr, health_score, risk_band, logins_30d, proposals_30d, tickets_90d, redo_90d
from ridgeline.at_risk
```

<DataTable data={risk} rows=15>
  <Column id=company_name title="Account"/>
  <Column id=current_plan title="Plan"/>
  <Column id=mrr title="MRR" fmt=usd0/>
  <Column id=health_score title="Health" contentType=colorscale colorScale={['#C2410C', '#FFF7ED']}/>
  <Column id=risk_band title="Band"/>
  <Column id=logins_30d title="Logins (30d)"/>
  <Column id=proposals_30d title="Proposals (30d)"/>
  <Column id=tickets_90d title="Tickets (90d)"/>
  <Column id=redo_90d title="Redos (90d)"/>
</DataTable>
