---
title: Metric glossary
---

Every KPI on this site, and every answer from the AI analyst, comes from one definition in the dbt semantic layer
(MetricFlow). Change a definition there and it changes everywhere.

A definition is only useful if it computes what it says. So each governed metric also has a second, independent
calculation: plain SQL written straight against the warehouse, without MetricFlow, starting from an earlier table
where one holds the same facts (MRR from the movement ledger rather than the daily MRR table, signups and spend
from the staging models). The nightly build and every CI run compare the two for every month since January 2024,
and fail if any month disagrees.

```sql glossary
select * from ridgeline.metric_glossary order by name
```

```sql summary
select count(*) as metrics,
       count(*) filter (where reconciled) as reconciled,
       sum(months_compared) as metric_months,
       min(months_compared) as months
from ridgeline.metric_glossary
```

<BigValue data={summary} value=metrics title="Governed metrics"/>
<BigValue data={summary} value=reconciled title="Agree with their independent check"/>
<BigValue data={summary} value=metric_months title="Metric-months compared" fmt=num0/>

## Definitions

<DataTable data={glossary} search=true rows=all>
  <Column id=label title="Metric" wrap=true/>
  <Column id=description title="Definition" wrap=true/>
  <Column id=latest_shown title="Last full month" align=right/>
  <Column id=latest_month_label title="Month"/>
  <Column id=check_status title="Check"/>
</DataTable>

"Last full month" is the latest complete month with a value. Ratios that need an outcome to mature (free to paid
in 60 days, 12-month NRR) stop earlier. Each metric's name in code and version are in its section below; the
version goes up whenever a definition changes its numbers on purpose, and the metric contract check in CI
enforces that.

## How each metric is checked

Open a metric to see the SQL that recomputes it. Each query returns one value per month, which must match the
governed metric for that month (to 6 decimals).

{#each glossary as m}

<Details title="{m.label} ({m.name})">

<p class="meta">
<b>Definition:</b> {m.description}<br/>
<b>Type:</b> {m.metric_type} · <b>version</b> {m.version} · <b>checked from</b> <code>{m.check_source}</code> ·
{m.months_compared} months compared, {m.mismatched_months} differ<br/>
{#if m.dimensions}<b>Can be broken down by:</b> {m.dimensions}{/if}
</p>

<pre class="sql">{m.check_sql}</pre>

</Details>

{/each}

The checks live in
[metric_glossary/checks.py](https://github.com/sky-five/ridgeline-analytics/tree/main/metric_glossary); run them
on a built warehouse with `python -m metric_glossary`.

<style>
  :global(article button.cursor-pointer) { text-align: left; }
  .meta { font-size: 0.85rem; color: #57534e; line-height: 1.6; }
  .sql { white-space: pre-wrap; font-size: 0.8rem; background: #fafaf9; border: 1px solid #e7e5e4; border-radius: 6px; padding: 0.6rem 0.75rem; }
</style>
