---
title: Contractor outcomes
---

Ridgeline only grows if its contractors win jobs. This page tracks what happens to the homeowner leads they work in
the app, and how good the roof measurement reports are. Close rate is the governed `lead_close_rate`: won leads
÷ leads that are no longer open.

```sql headline
select lead_close_rate, measurement_redo_rate from ridgeline.headline
```

```sql fast
select
    max(lead_close_rate) filter (where speed_bucket = 'lt_5m') as close_fast,
    max(lead_close_rate) filter (where speed_bucket = '5_60m') as close_slow
from ridgeline.lead_speed
```

<BigValue data={headline} value=lead_close_rate title="Lead close rate" fmt=pct1/>
<BigValue data={fast} value=close_fast title="Close rate, contacted in < 5 min" fmt=pct1/>
<BigValue data={fast} value=close_slow title="Close rate, 5–60 min" fmt=pct1/>
<BigValue data={headline} value=measurement_redo_rate title="Measurement redo rate" fmt=pct1 downIsGood=true/>

## Where leads end up

```sql outcomes
select replace(outcome_group, '_', ' ') as outcome, leads
from ridgeline.lead_outcomes
order by leads desc
```

<BarChart data={outcomes} x=outcome y=leads swapXY=true title="All homeowner leads by outcome" colorPalette={['#C2410C']}/>

## Speed to lead

```sql speed
select
    case speed_bucket
        when 'lt_5m' then '1. Under 5 min'
        when '5_60m' then '2. 5–60 min'
        when '1_24h' then '3. 1–24 hours'
        when 'gt_1d' then '4. Over a day'
        when 'missing' then '5. Contact time not logged'
        when 'not_contacted' then '6. Never contacted'
    end as first_contact,
    leads, lead_close_rate
from ridgeline.lead_speed
order by first_contact
```

<BarChart data={speed} x=first_contact y=lead_close_rate yFmt=pct0 title="Close rate by time to first contact" colorPalette={['#C2410C']} sort=false swapXY=true/>

Contractors who call back within five minutes close about twice as often. The AI Receptionist and SMS add-ons
reply to a lead straight away, so they are the natural upsell to test with slow responders. "Contact time not logged" is a data-quality gap,
not a speed: those leads were worked but the timestamp is missing, so speed-to-lead leaves them out.

```sql sources
select replace(lead_source, '_', ' ') as lead_source, leads, lead_close_rate, speed_to_lead_median_min
from ridgeline.lead_sources
order by lead_close_rate desc
```

<DataTable data={sources}>
  <Column id=lead_source title="Lead source"/>
  <Column id=leads title="Leads"/>
  <Column id=lead_close_rate title="Close rate" fmt=pct1 contentType=bar barColor="#FDBA74"/>
  <Column id=speed_to_lead_median_min title="Median minutes to first contact" fmt=num0/>
</DataTable>

## Benchmarks against peers

Each contractor's close rate last month, ranked against contractors with the same crew size. Only contractors with
at least five closed leads are ranked.

```sql bench
select crew_size, close_rate, median_speed_min
from ridgeline.contractor_benchmarks
```

```sql bench_summary
select crew_size,
       count(*) as contractors,
       quantile_cont(close_rate, 0.25) as p25,
       median(close_rate) as p50,
       quantile_cont(close_rate, 0.75) as p75,
       median(median_speed_min) as median_minutes
from ${bench}
group by 1
order by case crew_size when '1' then 1 when '2-5' then 2 when '6-15' then 3 else 4 end
```

<DataTable data={bench_summary}>
  <Column id=crew_size title="Crew size"/>
  <Column id=contractors title="Contractors"/>
  <Column id=p25 title="Close rate, 25th pct" fmt=pct0/>
  <Column id=p50 title="Median" fmt=pct0/>
  <Column id=p75 title="75th pct" fmt=pct0/>
  <Column id=median_minutes title="Median minutes to contact" fmt=num0/>
</DataTable>

<ScatterPlot data={bench} x=median_speed_min y=close_rate series=crew_size yFmt=pct0 xAxisTitle="Median minutes to first contact" title="Close rate vs speed to first contact, by crew size"/>

Within a crew size the link between a contractor's typical speed and their close rate is weak. The strong effect is
per lead (the speed chart above): a lead answered within five minutes is about twice as likely to close.

## Measurement report quality

```sql redo
select region, roof_type, measurement_redo_rate
from ridgeline.redo_rates
```

<Heatmap data={redo} x=roof_type y=region value=measurement_redo_rate valueFmt=pct1 colorScale={['#FFF7ED', '#C2410C']} title="Redo rate by region and roof type"/>

Complex roofs are redone most often, and Canada most of all. Redos lead to support tickets and later to churn
(see Retention and expansion), so this is the quality metric to watch.
