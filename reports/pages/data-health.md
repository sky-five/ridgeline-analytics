---
title: Data health
---

Can these numbers be trusted today? This page shows when each source last loaded and how the last dbt run went.

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

## Known gaps

- About 7% of homeowner leads that were worked have no first-contact time logged. Speed-to-lead excludes them
  rather than counting them as zero.
- Snowflake Cortex is blocked on the trial account, so ticket themes come from a classifier trained on 300
  hand-labelled tickets (100% on held-out labels).
