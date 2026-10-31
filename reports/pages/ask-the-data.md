---
title: Ask the data
---

Ridgeline's AI analyst is a Claude agent with six read-only tools over this warehouse: search the dbt catalog,
describe a model, trace lineage, list the governed metrics, query a metric through MetricFlow, and run a guarded
`SELECT`. It answers the way an analytics engineer would: find the right mart, prefer the governed metric, and cite
where the number came from.

This page shows a recorded run of the 20-question eval rather than a live chat box, so it costs nothing to visit.
Each answer was checked against a value computed straight from the marts.

```sql run
select *, strftime(strptime(ran_at, '%Y-%m-%dT%H:%M:%S'), '%b %d, %Y') as ran_on,
       strftime(cast(as_of as date), '%b %d, %Y') as data_as_of
from ridgeline.analyst_run
```

```sql stats
select median(seconds) as median_seconds, median(n_tool_calls) as median_tool_calls, sum(cost_usd) as total_cost,
       count(*) filter (where metric <> '') as via_metric
from ridgeline.analyst_answers
```

<BigValue data={run} value=correct title="Correct answers (of 20)"/>
<BigValue data={run} value=grounded title="Cited the right mart"/>
<BigValue data={stats} value=via_metric title="Answered through a governed metric"/>
<BigValue data={stats} value=median_seconds title="Median seconds per question" fmt=num0/>
<BigValue data={stats} value=total_cost title="Cost of all 20 at API rates" fmt=usd2/>

Run on <Value data={run} column=ran_on/>, with data as of <Value data={run} column=data_as_of/>. The rest of the
site rebuilds every night, so today's numbers may differ slightly from these answers.

## The 20 questions

Open a question to see the agent's full reply, the tools it called, and the governed metric or SQL behind the
number. The last one asks for something the warehouse doesn't hold, and the right reply is "no data", not a guess.

```sql answers
select * from ridgeline.analyst_answers order by n
```

{#each answers as a}

<Details title="{a.n}. {a.question}">

<div class="reply">{a.reply}</div>

<p class="meta">
<b>Check:</b> {a.correct ? '✅ correct' : '❌ wrong'} · {a.grounded ? 'cited the right mart' : 'did not cite the expected mart'} · expected <code>{a.truth}</code><br/>
<b>Tools:</b> {a.tool_calls} ({a.seconds.toFixed(0)} s)<br/>
<b>Sources:</b> {a.models}{#if a.metric} · governed metric <code>{a.metric}</code>{/if}
</p>

{#if a.sql}
<pre class="sql">{a.sql}</pre>
{/if}

</Details>

{/each}

## Try it yourself

The same tools run as an MCP server, so you can point Claude Code or Claude Desktop at a local copy of the
warehouse:

```bash
git clone https://github.com/sky-five/ridgeline-analytics && cd ridgeline-analytics
python scripts/run_all.py                                   # build the warehouse
claude mcp add ridgeline -- python -m analyst.server        # then ask Claude about Ridgeline
```

The guardrails live in `analyst/sql_guard.py`: the database opens read-only, file and network access are turned off,
every statement must parse as a single `SELECT`, and rows and run time are capped.

<style>
  :global(article button.cursor-pointer) { text-align: left; }
  .reply { white-space: pre-wrap; line-height: 1.55; margin: 0.25rem 0 0.75rem; }
  .meta { font-size: 0.85rem; color: #57534e; line-height: 1.6; }
  .sql { white-space: pre-wrap; font-size: 0.8rem; background: #fafaf9; border: 1px solid #e7e5e4; border-radius: 6px; padding: 0.6rem 0.75rem; }
</style>
