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
