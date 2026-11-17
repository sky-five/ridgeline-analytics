---
title: Operations speed-to-decision
---

**Simulated data**, separate from the roofing-software company on the rest of this site: a claims operation with
three sites (east, central, west) and two lines (home, auto), so six teams, from <Value data={summary} column=first_day/>
to <Value data={summary} column=as_of/> (<Value data={summary} column=calls_offered fmt=num0/> calls offered, <Value data={summary} column=claims_opened fmt=num0/> new claims). A staff cut, a slow rise in handle time and a
windstorm are planted on purpose. The page shows the three things to look at today, the seven daily metrics team
by team with the flagged days marked, how well the flag rule found the planted events, a so-what per metric, and
the metric definitions the rule reads its thresholds from.

Code, dbt models, tests and [today's note](https://github.com/sky-five/ridgeline-analytics/blob/main/ops_daily/results/today.md):
[ops_daily/](https://github.com/sky-five/ridgeline-analytics/tree/main/ops_daily). The simulation is seeded, so
these numbers do not move with the nightly build.

```sql summary
select * from ridgeline.ops_summary
```

## The half-year

<BigValue data={summary} value=calls_offered title="Calls offered" fmt=num0/>
<BigValue data={summary} value=service_level title="Answered within 60 s" fmt=pct1/>
<BigValue data={summary} value=abandon_rate title="Abandoned" fmt=pct1/>
<BigValue data={summary} value=avg_handle_minutes title="Handle time, minutes" fmt=num1/>
<BigValue data={summary} value=open_backlog_as_of title="Open claims, last day" fmt=num0/>

The usual end-of-day backlog across the operation this year is <Value data={summary} column=open_backlog_median fmt=num0/>
open claims (the median day); on the last day it is <Value data={summary} column=open_backlog_as_of fmt=num0/>.

## Three things to look at on <Value data={summary} column=as_of_label/>

```sql today
select * from ridgeline.ops_today order by rank
```

Each metric is compared with the same weekday over the previous six weeks. The list keeps each team's furthest-out
flagged metric and shows the three teams furthest out.

{#each today as w}

- <b>{w.rank}. {w.team}: {w.metric_label.toLowerCase()} {w.value_text}</b>, usually {w.baseline_text} on that weekday.{w.also_flagged ? ' Also flagged: ' + w.also_flagged + '.' : ''} First check: {w.first_check}

{/each}

<DataTable data={today} rows=all>
  <Column id=rank title="#"/>
  <Column id=team title="Team"/>
  <Column id=metric_label title="Metric"/>
  <Column id=value_text title="Today"/>
  <Column id=baseline_text title="Usual"/>
  <Column id=score title="Spreads out" fmt=num1/>
</DataTable>

## The seven metrics, team by team

```sql team_choice
select distinct team from ridgeline.ops_metric_day order by team
```

<Dropdown data={team_choice} name=team value=team title="Team" defaultValue="Central home"/>

Black is the day's value, grey the median of the same weekday over the previous six weeks (from the seventh week),
and orange dots the flagged days.

```sql m_calls_offered
select day, 'The day' as series, value from ridgeline.ops_metric_day
where team = '${inputs.team.value}' and metric = 'calls_offered'
union all
select day, 'Same weekday, 6-week median', baseline from ridgeline.ops_metric_day
where team = '${inputs.team.value}' and metric = 'calls_offered' and baseline_days = 6
order by day
```

```sql f_calls_offered
select day, value from ridgeline.ops_metric_day
where team = '${inputs.team.value}' and metric = 'calls_offered' and flagged
```

<LineChart data={m_calls_offered} x=day y=value series=series yFmt=num0 title="Calls offered" colorPalette={['#111827', '#9CA3AF']}>
  {#if f_calls_offered.length > 0}
  <ReferencePoint data={f_calls_offered} x=day y=value color="#C2410C" symbolSize=8/>
  {/if}
</LineChart>

```sql m_service_level
select day, 'The day' as series, value from ridgeline.ops_metric_day
where team = '${inputs.team.value}' and metric = 'service_level'
union all
select day, 'Same weekday, 6-week median', baseline from ridgeline.ops_metric_day
where team = '${inputs.team.value}' and metric = 'service_level' and baseline_days = 6
order by day
```

```sql f_service_level
select day, value from ridgeline.ops_metric_day
where team = '${inputs.team.value}' and metric = 'service_level' and flagged
```

<LineChart data={m_service_level} x=day y=value series=series yFmt=pct0 title="Service level" colorPalette={['#111827', '#9CA3AF']}>
  {#if f_service_level.length > 0}
  <ReferencePoint data={f_service_level} x=day y=value color="#C2410C" symbolSize=8/>
  {/if}
</LineChart>

```sql m_abandon_rate
select day, 'The day' as series, value from ridgeline.ops_metric_day
where team = '${inputs.team.value}' and metric = 'abandon_rate'
union all
select day, 'Same weekday, 6-week median', baseline from ridgeline.ops_metric_day
where team = '${inputs.team.value}' and metric = 'abandon_rate' and baseline_days = 6
order by day
```

```sql f_abandon_rate
select day, value from ridgeline.ops_metric_day
where team = '${inputs.team.value}' and metric = 'abandon_rate' and flagged
```

<LineChart data={m_abandon_rate} x=day y=value series=series yFmt=pct0 title="Abandon rate" colorPalette={['#111827', '#9CA3AF']}>
  {#if f_abandon_rate.length > 0}
  <ReferencePoint data={f_abandon_rate} x=day y=value color="#C2410C" symbolSize=8/>
  {/if}
</LineChart>

```sql m_avg_handle_minutes
select day, 'The day' as series, value from ridgeline.ops_metric_day
where team = '${inputs.team.value}' and metric = 'avg_handle_minutes'
union all
select day, 'Same weekday, 6-week median', baseline from ridgeline.ops_metric_day
where team = '${inputs.team.value}' and metric = 'avg_handle_minutes' and baseline_days = 6
order by day
```

```sql f_avg_handle_minutes
select day, value from ridgeline.ops_metric_day
where team = '${inputs.team.value}' and metric = 'avg_handle_minutes' and flagged
```

<LineChart data={m_avg_handle_minutes} x=day y=value series=series yFmt=num1 title="Average handle time, minutes" colorPalette={['#111827', '#9CA3AF']}>
  {#if f_avg_handle_minutes.length > 0}
  <ReferencePoint data={f_avg_handle_minutes} x=day y=value color="#C2410C" symbolSize=8/>
  {/if}
</LineChart>

```sql m_claims_opened
select day, 'The day' as series, value from ridgeline.ops_metric_day
where team = '${inputs.team.value}' and metric = 'claims_opened'
union all
select day, 'Same weekday, 6-week median', baseline from ridgeline.ops_metric_day
where team = '${inputs.team.value}' and metric = 'claims_opened' and baseline_days = 6
order by day
```

```sql f_claims_opened
select day, value from ridgeline.ops_metric_day
where team = '${inputs.team.value}' and metric = 'claims_opened' and flagged
```

<LineChart data={m_claims_opened} x=day y=value series=series yFmt=num0 title="New claims" colorPalette={['#111827', '#9CA3AF']}>
  {#if f_claims_opened.length > 0}
  <ReferencePoint data={f_claims_opened} x=day y=value color="#C2410C" symbolSize=8/>
  {/if}
</LineChart>

```sql m_claims_closed
select day, 'The day' as series, value from ridgeline.ops_metric_day
where team = '${inputs.team.value}' and metric = 'claims_closed'
union all
select day, 'Same weekday, 6-week median', baseline from ridgeline.ops_metric_day
where team = '${inputs.team.value}' and metric = 'claims_closed' and baseline_days = 6
order by day
```

```sql f_claims_closed
select day, value from ridgeline.ops_metric_day
where team = '${inputs.team.value}' and metric = 'claims_closed' and flagged
```

<LineChart data={m_claims_closed} x=day y=value series=series yFmt=num0 title="Claims closed" colorPalette={['#111827', '#9CA3AF']}>
  {#if f_claims_closed.length > 0}
  <ReferencePoint data={f_claims_closed} x=day y=value color="#C2410C" symbolSize=8/>
  {/if}
</LineChart>

```sql m_open_backlog
select day, 'The day' as series, value from ridgeline.ops_metric_day
where team = '${inputs.team.value}' and metric = 'open_backlog'
union all
select day, 'Same weekday, 6-week median', baseline from ridgeline.ops_metric_day
where team = '${inputs.team.value}' and metric = 'open_backlog' and baseline_days = 6
order by day
```

```sql f_open_backlog
select day, value from ridgeline.ops_metric_day
where team = '${inputs.team.value}' and metric = 'open_backlog' and flagged
```

<LineChart data={m_open_backlog} x=day y=value series=series yFmt=num0 title="Open claims at the end of the day" colorPalette={['#111827', '#9CA3AF']}>
  {#if f_open_backlog.length > 0}
  <ReferencePoint data={f_open_backlog} x=day y=value color="#C2410C" symbolSize=8/>
  {/if}
</LineChart>

```sql team_flags
select day, metric_label, value_text, baseline_text, score, planted_event from ridgeline.ops_flags
where team = '${inputs.team.value}' order by day desc, abs(score) desc
```

<DataTable data={team_flags} rows=10 title="Every flagged day for the team, newest first">
  <Column id=day title="Day"/>
  <Column id=metric_label title="Metric"/>
  <Column id=value_text title="Value"/>
  <Column id=baseline_text title="Usual"/>
  <Column id=score title="Spreads out" fmt=num1/>
  <Column id=planted_event title="Planted event"/>
</DataTable>

## Does the rule find what matters?

Back-checked on every day from <Value data={summary} column=scored_from/> (the first with six weeks behind it) to <Value data={summary} column=as_of/>: <Value data={summary} column=scored_values fmt=num0/> scored values, <Value data={summary} column=flags fmt=num0/> flagged.

```sql backcheck
select event, team, from_day, cause, days_to_flag_cause, days_on_watchlist || ' of ' || days_since_start as on_list,
       metrics_flagged
from ridgeline.ops_backcheck order by from_day desc
```

<DataTable data={backcheck} rows=all>
  <Column id=event title="Planted event"/>
  <Column id=team title="Team"/>
  <Column id=from_day title="From"/>
  <Column id=cause title="Shows up in"/>
  <Column id=days_to_flag_cause title="Days to flag it"/>
  <Column id=on_list title="Days on the list"/>
</DataTable>

{#each backcheck as e}

- <b>{e.event}</b>: {e.team} was flagged on {e.metrics_flagged}.

{/each}

```sql false_flags
select metric_label, false_flags from ridgeline.ops_false_flags order by metric_sort
```

<BarChart data={false_flags} x=metric_label y=false_flags swapXY=true sort=false yFmt=num0
  title="Flags on teams with nothing planted, by metric" colorPalette={['#9CA3AF']}/>

Teams with nothing planted were flagged <Value data={summary} column=false_flags fmt=num0/> times
(<Value data={summary} column=false_flag_rate fmt=pct1/> of their scored values). That still puts a false item on
the list on <Value data={summary} column=days_with_a_false_watchlist_item fmt=num0/> of <Value data={summary} column=scored_days fmt=num0/> days, so treat the third item as a question, not an alarm.

The slow rise is the rule's weak spot. East home's handle time was flagged <Value data={summary} column=handle_time_creep_days_to_flag_cause fmt=num0/> days in, but a six-week baseline takes
a lasting change in as normal: by the last day three of the six Tuesdays behind it were already raised, so its
handle time was no longer flagged and only its abandon rate kept the team on the list. A metric with a target (handle
time against plan) needs that target as a second check.

## So what, metric by metric

```sql so_what
select label, body from ridgeline.ops_so_what order by metric_sort
```

{#each so_what as m}

- <b>{m.label}.</b> {m.body}

{/each}

## Metric definitions

The [definitions sheet](https://github.com/sky-five/ridgeline-analytics/blob/main/ops_daily/dbt/seeds/metric_definitions.csv)
is a dbt seed; the flag rule reads its thresholds from it, so the sheet and the rule can't drift apart.

```sql definitions
select * from ridgeline.ops_definitions order by metric_sort
```

{#each definitions as d}

- <b>{d.label}</b> ({d.unit}): {d.definition} Formula: <code>{d.formula}</code> from <code>{d.source}</code>. Better when: {d.good_direction}. Flagged only if it moves at least {d.min_change} (and 3 spreads). First check: {d.first_check}

{/each}
