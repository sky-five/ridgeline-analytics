---
title: Ready for sales
---

Every free account gets a score from what it did in its **first 14 days, before paying**: proposals sent,
measurements ordered, logins, channel and crew size. The model was trained on 2024–2025 signups and is checked here
on 2026 signups it never saw.

```sql deciles
select decile, accounts, paid_60d_rate from ridgeline.pqa_deciles order by decile
```

```sql lift
select
    max(case when decile = 10 then paid_60d_rate end) as top_rate,
    sum(paid_60d_rate * accounts) / sum(accounts) as avg_rate,
    max(case when decile = 10 then paid_60d_rate end) / (sum(paid_60d_rate * accounts) / sum(accounts)) as lift
from ${deciles}
```

<BigValue data={lift} value=top_rate title="Top 10% convert" fmt=pct0/>
<BigValue data={lift} value=avg_rate title="Average" fmt=pct0/>
<BigValue data={lift} value=lift title="Lift" fmt='0.0"×"'/>

<BarChart data={deciles} x=decile y=paid_60d_rate yFmt=pct0 title="Paid within 60 days, by score decile (10 = highest)" colorPalette={['#C2410C']}/>

## Call list

Free accounts 14–45 days old, highest score first, with the signals behind each score.

```sql call_list
select * from ridgeline.call_list
```

<DataTable data={call_list} search=true rows=15>
  <Column id=company_name title="Company"/>
  <Column id=channel title="Channel"/>
  <Column id=crew_size title="Crew"/>
  <Column id=signed_up title="Signed up"/>
  <Column id=score_model title="Score" fmt=pct0 contentType=colorscale scaleColor="#C2410C"/>
  <Column id=score_points title="Points"/>
  <Column id=top_reasons title="Why" wrap=true/>
</DataTable>

## Are reps calling the best accounts quickly?

```sql followups
select * from ridgeline.followup_outcomes
```

```sql reps
select * from ridgeline.rep_followups
```

<DataTable data={followups}>
  <Column id=follow_up title=""/>
  <Column id=accounts title="Top-decile accounts"/>
  <Column id=paid_60d_rate title="Paid within 60 days" fmt=pct0/>
</DataTable>

<BarChart data={reps} x=rep y=called_within_3d_rate yFmt=pct0 title="Share of top accounts called within 3 days of becoming eligible" colorPalette={['#F59E0B']}/>
