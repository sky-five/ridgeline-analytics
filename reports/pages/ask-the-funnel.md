---
title: Ask the funnel
---

Type a question about the acquisition funnel. The panel answers only with a governed metric from the dbt semantic
layer (the same MetricFlow definitions as the rest of the site and the [metric glossary](/metrics)), and says so
when a question doesn't name one. There is no language model behind it: it matches the question's words against a
short list of phrases for six metrics, an optional channel, and an optional month or year, then looks the value up.
Nothing is computed on this page, so it can't make up a definition or a number.

<TextInput name=question title="Question" defaultValue="What was CAC for Google Ads in March 2026?"/>

Try: *How many signups last month?* · *Free to paid by channel in 2025* · *Ad spend on trade shows in June 2026* ·
*Activation rate in 2026* · *What is our churn rate?* (refused: churn is not a funnel metric)

```sql answer
with q as (
    select
        ' ' || trim(regexp_replace(lower(${inputs.question.sql}), '[^a-z0-9]+', ' ', 'g')) || ' ' as words,
        nullif(regexp_extract(lower(${inputs.question.sql}), '(20[0-9][0-9])', 1), '') as asked_year
),

hits as (
    select
        v.kind,
        v.target,
        row_number() over (partition by v.kind order by length(v.phrase) desc, v.target) as rank_in_kind
    from ridgeline.funnel_vocab as v, q
    where contains(q.words, ' ' || v.phrase || ' ')
),

asked as (
    select
        any_value(q.asked_year) as asked_year,
        max(h.target) filter (where h.kind = 'metric' and h.rank_in_kind = 1) as metric,
        max(h.target) filter (where h.kind = 'channel' and h.rank_in_kind = 1) as channel,
        max(h.target) filter (where h.kind = 'month' and h.rank_in_kind = 1) as month_num,
        coalesce(bool_or(h.kind = 'breakdown'), false) as by_channel
    from q left join hits as h on true
),

totals as (
    select a.*
    from ridgeline.funnel_answers as a, asked as k
    where
        a.metric = k.metric
        and a.channel = 'all'
        and a.grain = case when k.asked_year is not null and k.month_num is null then 'year' else 'month' end
        and (k.asked_year is null or a.year = k.asked_year)
        and (k.month_num is null or a.month_num = k.month_num)
        and a.value is not null
),

chosen as (
    -- a period named in the question: the latest one that matches; otherwise the latest complete month
    select max(t.period) as period
    from totals as t, asked as k
    where t.complete or k.asked_year is not null or k.month_num is not null
),

answers as (
    select
        'answer' as status,
        a.label || case when a.channel = 'all' then '' else ' (' || replace(a.channel, '_', ' ') || ')' end
        || ', ' || a.period_label || ': ' || a.value_shown
        || case when a.complete then '' else ' (not final yet: the period is still open or its outcomes are still maturing)' end
        as reply,
        a.metric,
        a.label,
        a.description,
        a.channel,
        a.period_label,
        a.value,
        a.value_shown,
        a.complete,
        a.mf_query
    from ridgeline.funnel_answers as a, asked as k, chosen as c
    where
        a.metric = k.metric
        and a.grain = case when k.asked_year is not null and k.month_num is null then 'year' else 'month' end
        and a.period = c.period
        and case
            when k.channel is not null then a.channel = k.channel
            when k.by_channel then a.channel <> 'all'
            else a.channel = 'all'
        end
),

fallback as (
    select
        case when k.metric is null then 'refused' else 'no_data' end as status,
        case
            when k.metric is null
                then 'I only answer from governed funnel metrics: signups, activation rate, free to paid (60 days), '
                || 'paid conversions, ad spend and CAC, for a month, a year or a channel. '
                || 'This question does not name one of them, so there is no governed number to give.'
            else 'The governed metric ' || k.metric || ' has no value for that period'
                || coalesce(' and channel (' || replace(k.channel, '_', ' ') || ')', '') || '.'
        end as reply,
        k.metric,
        null as label,
        null as description,
        k.channel,
        null as period_label,
        null as value,
        null as value_shown,
        null as complete,
        null as mf_query
    from asked as k
    where not exists (select 1 from answers)
)

select * from answers
union all by name
select * from fallback
order by value desc nulls last, channel
```

{#if answer.length && answer[0].status === 'answer'}

{#each answer as a}
<p class="answer">{a.reply}</p>
{/each}

<p class="meta">
<b>Governed metric:</b> <code>{answer[0].metric}</code> ({answer[0].label}): {answer[0].description}<br/>
<b>Same query from the command line:</b> <code>{answer[0].mf_query}</code>
</p>

{:else if answer.length}

<p class="answer refused">{answer[0].reply}</p>

{/if}

## What it understands

```sql metrics
select metric, any_value(label) as label, any_value(description) as description,
       string_agg(distinct v.phrase, ', ' order by v.phrase) as phrases
from ridgeline.funnel_answers as a
join ridgeline.funnel_vocab as v on v.kind = 'metric' and v.target = a.metric
group by metric
order by metric
```

<DataTable data={metrics} rows=all>
  <Column id=label title="Metric" wrap=true/>
  <Column id=description title="Definition" wrap=true/>
  <Column id=phrases title="Phrases that ask for it" wrap=true/>
</DataTable>

Channels can be named (Google Ads, Facebook, trade show, supplier partner, referral, organic) or asked for all at
once ("by channel"). A month without a year means the latest one; no period means the latest month whose
numbers are final. Free to paid, paid conversions and CAC follow signups for 60 days, so their latest final month
is about two months back, and an answer for a period that isn't final says so. When several phrases match, the
longest wins: "spend per paid conversion" is CAC, not ad spend.

The routing is one SQL query over two tables, and this page runs it in your browser. The repo has the same query
in `funnel_ask/route.sql`, with tests for routing, refusals and quoting, and a test that the values here match
MetricFlow ([funnel_ask/](https://github.com/sky-five/ridgeline-analytics/tree/main/funnel_ask)).

<style>
  .answer { font-size: 1.15rem; font-weight: 600; margin: 0.4rem 0; }
  .refused { font-weight: 400; color: #9a3412; }
  .meta { font-size: 0.85rem; color: #57534e; line-height: 1.6; margin-top: 0.75rem; }
</style>
