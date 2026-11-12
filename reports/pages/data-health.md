---
title: Data health
---

Can these numbers be trusted today? This page shows when each source last loaded, whether each table's latest
day of data looks normal, and how the last dbt run went.

## How to read this page

```sql example
select table_name, grade, reason
from ridgeline.table_health
order by case grade when 'red' then 0 when 'amber' then 1 else 2 end, table_name
limit 1
```

1. **Did the pipelines run?** In the first table, every source system should say `fresh`. `warn` or `error`
   means that system has not loaded for a while, so every number built from it may be out of date.
2. **Does today's data look normal?** The scorecard below grades each source table green, amber or red.
   Green: use the numbers. Amber: usable, but read the reason first. Red: do not quote numbers built on that
   table for this day.
3. **Read the reason, not just the colour.** Each table gets one sentence with its own numbers. The scorecard
   lists the worst grade first; today's first row is **<Value data={example} column=table_name/>**
   (<Value data={example} column=grade/>): "<Value data={example} column=reason/>".
4. **Check the build.** Under *Last dbt build*, passing should equal the total. A failing test stops the
   nightly build before it publishes, so the live site keeps the previous build rather than broken numbers.
5. **Look up any word** in the [glossary](#glossary) at the bottom. Business numbers (MRR, signups, close rate)
   are defined on the [Metric glossary](/metrics/) page.

## Pipeline loads

```sql sources
select source_system, strftime(last_loaded_at, '%Y-%m-%d %H:%M') as last_loaded_utc, hours_before_build,
       freshness, loads, strftime(built_at, '%Y-%m-%d %H:%M') as built_utc
from ridgeline.source_loads
order by source_system
```

Site built <Value data={sources} column=built_utc/> UTC.

<DataTable data={sources}>
  <Column id=source_system title="Source system"/>
  <Column id=last_loaded_utc title="Last successful load (UTC)"/>
  <Column id=hours_before_build title="Hours before build"/>
  <Column id=freshness title="Freshness"/>
  <Column id=loads title="Loads"/>
</DataTable>

Freshness rule: warn after 36 hours without a successful load, fail after 72.

## Table health scorecard

A load can succeed and still bring the wrong day: late, half empty, doubled, or with a column suddenly blank.
Each source table's batch for the day is graded against that table's own last 28 days.

```sql health
select table_name, grade, reason, freshness_grade, volume_grade, null_rate_grade, rows_today, usual_rows,
       strftime(day, '%Y-%m-%d') as day,
       case grade when 'red' then 0 when 'amber' then 1 else 2 end as grade_order
from ridgeline.table_health
order by grade_order, table_name
```

```sql health_counts
select count(*) filter (where grade = 'green') as green, count(*) filter (where grade = 'amber') as amber,
       count(*) filter (where grade = 'red') as red, max(day) as day
from ${health}
```

Day graded: <Value data={health_counts} column=day/>

<BigValue data={health_counts} value=green title="Green"/>
<BigValue data={health_counts} value=amber title="Amber"/>
<BigValue data={health_counts} value=red title="Red"/>

<DataTable data={health} rows=all>
  <Column id=table_name title="Table"/>
  <Column id=grade title="Grade"/>
  <Column id=reason title="Reason" wrap=true/>
  <Column id=freshness_grade title="Freshness"/>
  <Column id=volume_grade title="Volume"/>
  <Column id=null_rate_grade title="Null rate"/>
  <Column id=rows_today title="Rows" fmt=num0/>
  <Column id=usual_rows title="Usual a day" fmt=num0/>
</DataTable>

How the grades work: freshness compares the hours since the table's last row with its longest gap in 28 days
(amber past it, red past three times it, never stricter than 24 hours). Volume and null rate count spreads from
the usual day (amber past 3, red past 6); the spread is never smaller than what random noise gives a table that
size, so a table with four rows a day is not flagged for having two. Code and tests:
[data_health/](https://github.com/sky-five/ridgeline-analytics/tree/main/data_health).

## Last dbt build

```sql tests
select resource_type, status, nodes from ridgeline.test_summary
```

```sql totals
select sum(nodes) as total,
       sum(case when status in ('pass', 'success') then nodes else 0 end) as passing,
       max(generated_at) as built_at
from ${tests}, (select max(generated_at) as generated_at from ridgeline.dbt_run_results)
```

<BigValue data={totals} value=passing title="Passing"/>
<BigValue data={totals} value=total title="Models, tests and snapshots"/>

<DataTable data={tests}>
  <Column id=resource_type title="Type"/>
  <Column id=status title="Status"/>
  <Column id=nodes title="Count"/>
</DataTable>

Tests include unique and not-null keys, accepted values, relationships, enforced contracts on marts, unit tests
for business logic (MRR movements, the 60-day cutoff, speed-to-lead buckets), and reconciliations
(every subscription invoice equals the MRR log; daily MRR ties to account MRR).

## Glossary

Every label on this page, in plain words. The thresholds here are read from the code that applies them, so
they change when the rules do.

```sql glossary
select term, shown_as, meaning, what_to_do from ridgeline.data_health_glossary
```

<DataTable data={glossary} rows=all search=true>
  <Column id=term title="Term"/>
  <Column id=shown_as title="Shown on the page as" wrap=true/>
  <Column id=meaning title="What it means" wrap=true/>
  <Column id=what_to_do title="What to do about it" wrap=true/>
</DataTable>

## Known gaps

- About 7% of homeowner leads that were worked have no first-contact time logged. Speed-to-lead excludes them
  rather than counting them as zero.
- Snowflake Cortex is blocked on the trial account, so ticket themes come from a classifier trained on 300
  hand-labelled tickets (100% on held-out labels).
