---
title: Renewals at risk
---

A learning project on **simulated** data. Every live subscription renews monthly, so each one is a renewal at risk
every month. This page lists them on 2026-07-01, the morning after the fixed simulated history in
[customer_health/](https://github.com/sky-five/ridgeline-analytics/tree/main/customer_health) ends, scored two ways:
a hand-weighted health score (0-100, lower is worse) and a logistic-regression churn model (chance of a cancel in
the next 60 days). Each method flags its riskiest fifth. Unlike the health bands on the Retention page, this list does
not move with the nightly build: it is the output of one fixed, tested run.

```sql live
select
    count(*) as accounts,
    sum(mrr_usd) as mrr,
    count(*) filter (where flagged_by_score) as by_score,
    count(*) filter (where flagged_by_model) as by_model,
    count(*) filter (where flagged_by_score and flagged_by_model) as by_both,
    sum(mrr_usd) filter (where flagged_by_score or flagged_by_model) as mrr_flagged
from ridgeline.health_at_risk
```

<BigValue data={live} value=accounts title="Live subscriptions" fmt=num0/>
<BigValue data={live} value=by_score title="Flagged by the score" fmt=num0/>
<BigValue data={live} value=by_model title="Flagged by the model" fmt=num0/>
<BigValue data={live} value=by_both title="Flagged by both" fmt=num0/>
<BigValue data={live} value=mrr_flagged title="MRR flagged by either" fmt=usd0k/>

## How much to trust the flags

Both methods were compared on <Value data={cmp} column=test_accounts fmt=num0/> accounts held out from fitting, over
monthly snapshots where the outcome is known. On average <Value data={cmp} column=churn_rate fmt=pct1/> of snapshots
cancel within 60 days.

```sql cmp
select * from ridgeline.health_compare
```

<DataTable data={cmp}>
  <Column id=method title="Method"/>
  <Column id=auc title="ROC AUC" fmt=num3/>
  <Column id=churn_in_riskiest title="Churn in riskiest 20%" fmt=pct1/>
  <Column id=churners_caught title="Share of churners in that 20%" fmt=pct1/>
</DataTable>

Both are only a little better than chance (an AUC of 0.5 is a coin flip). In this simulation a cancel is mostly
random each month, and the clearest drivers are crew size and a recent re-measure request. Read the list as "call
these first", not as a prediction. The score's reasons are easier to act on; the model mostly agrees with them.

## The list

```sql flagged
select account_id, company_name, region, crew_size, plan, mrr_usd, health_score, model_risk,
       case when flagged_by_score and flagged_by_model then 'both'
            when flagged_by_score then 'score' else 'model' end as flagged_by,
       reasons
from ridgeline.health_at_risk
where flagged_by_score or flagged_by_model
order by health_score, model_risk desc
```

<DataTable data={flagged} search=true rows=25>
  <Column id=company_name title="Account"/>
  <Column id=region/>
  <Column id=crew_size title="Crew"/>
  <Column id=plan/>
  <Column id=mrr_usd title="MRR" fmt=usd0/>
  <Column id=health_score title="Health score"/>
  <Column id=model_risk title="Model risk" fmt=pct0/>
  <Column id=flagged_by title="Flagged by"/>
  <Column id=reasons title="Why the score is low"/>
</DataTable>

```sql by_crew
select crew_size,
       count(*) as accounts,
       avg(health_score) as avg_score,
       avg(model_risk) as avg_model_risk
from ridgeline.health_at_risk
group by 1
order by case crew_size when '1' then 0 when '2-5' then 1 when '6-15' then 2 else 3 end
```

<BarChart data={by_crew} x=crew_size y=avg_model_risk yFmt=pct0 title="Average model risk by crew size" colorPalette={['#C2410C']} sort=false/>
