---
title: Raw tables vs governed metrics
---

Is an AI analyst more reliable when it can only use governed metrics? The same 25 business questions were asked
twice: once with nothing but the raw tables as the loaders landed them and a SQL tool, once with nothing but the
27 MetricFlow metrics and no SQL. Each answer was checked against the answer key, which is computed from the same
governed metrics on the same warehouse day.

This page shows recorded runs, so it costs nothing to visit and its numbers change only when a new run is
committed. One run per arm and question: a demonstration, not a benchmark. Other models score differently.

```sql scores
select * from ridgeline.eval_scores
```

```sql lift
select r.run, r.model, r.ran_on, r.as_of,
       r.correct as raw_correct, g.correct as governed_correct, r.total,
       r.correct_on_substance as raw_on_substance,
       g.correct - r.correct as lift, round(100 * (g.accuracy - r.accuracy)) as lift_points,
       r.errors as raw_hit_cap,
       r.median_tool_calls as raw_tool_calls, g.median_tool_calls as governed_tool_calls
from ${scores} r
join ${scores} g on g.run_order = r.run_order and g.arm = 'governed'
where r.arm = 'raw'
order by r.run_order
```

```sql first_run
select * from ${lift} limit 1
```

## Accuracy lift from governed metrics

<BigValue data={first_run} value=governed_correct title="Governed metrics, correct of 25"/>
<BigValue data={first_run} value=raw_correct title="Raw tables, correct of 25"/>
<BigValue data={first_run} value=lift_points title="Accuracy lift, percentage points"/>
<BigValue data={first_run} value=raw_on_substance title="Raw tables, right on substance"/>

The headline is the <Value data={first_run} column=run/> run, recorded on <Value data={first_run} column=ran_on/>
with data as of <Value data={first_run} column=as_of/>. "Right on substance" also counts raw answers that named
the right thing in their own words but not in the form the scorer accepts (marked below).

```sql chart
select run, case arm when 'raw' then 'Raw tables' else 'Governed metrics' end as arm, accuracy
from ${scores}
order by run_order, arm desc
```

<BarChart data={chart} x=run y=accuracy series=arm type=grouped yFmt=pct0 yMax=1
  title="Share of the 25 questions answered correctly" colorPalette={['#C2410C', '#9CA3AF']}/>

<DataTable data={lift}>
  <Column id=run title="Model"/>
  <Column id=raw_correct title="Raw tables"/>
  <Column id=governed_correct title="Governed metrics"/>
  <Column id=lift title="Lift (answers)"/>
  <Column id=raw_on_substance title="Raw, substance"/>
  <Column id=raw_hit_cap title="Raw, capped"/>
</DataTable>

No question was answered right on raw tables and wrong with governed metrics, in either run.

## By question area

```sql areas
select c.category as area, c.run,
       sum(c.correct) filter (where c.arm = 'raw')::int || ' / ' || max(c.total)::int as raw_tables,
       sum(c.correct) filter (where c.arm = 'governed')::int || ' / ' || max(c.total)::int as governed_metrics
from ridgeline.eval_categories c
group by c.category, c.run, c.run_order
order by c.category, c.run_order
```

<DataTable data={areas} rows=20>
  <Column id=area title="Area"/>
  <Column id=run title="Model"/>
  <Column id=raw_tables title="Raw tables"/>
  <Column id=governed_metrics title="Governed metrics"/>
</DataTable>

Revenue questions mostly survive raw tables: MRR is one column of the subscription change log. The misses
cluster on definition questions (trial-to-paid, activation, lead close rate, CAC, retention), where the raw tables
don't say what the business means, so the agent picks a definition and returns a confident number.

## Failure examples

Every question the raw-table arm got wrong and the governed arm got right. Open one to see the trap the question
was written to catch, the definition the raw arm said it used, and the last query each arm ran.

```sql failures
select * from ridgeline.eval_questions
where outcome = 'only governed right'
order by run_order, n
```

{#each failures as f}

<Details title="{f.run}: {f.question}">

<p class="meta">
<b>Right answer:</b> <code>{f.truth}</code> · <b>raw tables said:</b> <code>{f.raw_answer}</code> · <b>governed metrics said:</b> <code>{f.governed_answer}</code><br/>
<b>Area:</b> {f.category} · <b>raw tool calls:</b> {f.raw_tool_calls}{#if f.raw_error} · stopped at the call cap without an answer{/if}
</p>

{#if f.form_only_note}
<p class="note">Right on substance, wrong on form: {f.form_only_note}</p>
{/if}

<p><b>The trap:</b> {f.trap}</p>

{#if f.raw_definition}
<p><b>Definition the raw arm used:</b> {f.raw_definition}</p>
{/if}

{#if f.raw_sql}
<p class="meta"><b>Raw arm's last SQL</b></p>
<pre class="sql">{f.raw_sql}</pre>
{/if}

{#if f.governed_query}
<p class="meta"><b>Governed arm's last metric query</b></p>
<pre class="sql">{f.governed_query}</pre>
{/if}

</Details>

{/each}

## How it was run

The raw arm gets `list_raw_tables` and `run_raw_sql` over a separate DuckDB file holding only the 11 loaded
tables, so no mart, view or metric can be reached. The governed arm gets `list_governed_metrics` and
`query_governed_metric` and no SQL. Each arm is its own MCP server; the prompts, caps (12 model calls per answer)
and scoring are the same for every model. Code, questions and the recorded runs are in
[semantic_eval/](https://github.com/sky-five/ridgeline-analytics/tree/main/semantic_eval); any committed run
replays without an API key:

```bash
python -m semantic_eval.run --replay semantic_eval/results/raw-vs-governed-2026-11-03.json
```

<style>
  :global(article button.cursor-pointer) { text-align: left; }
  .meta { font-size: 0.85rem; color: #57534e; line-height: 1.6; }
  .note { font-size: 0.85rem; color: #92400e; }
  .sql { white-space: pre-wrap; font-size: 0.8rem; background: #fafaf9; border: 1px solid #e7e5e4; border-radius: 6px; padding: 0.6rem 0.75rem; }
</style>
