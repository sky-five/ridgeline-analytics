-- Route one plain-English question to governed funnel metric values, or refuse.
-- {question} is a quoted SQL string literal. Reads only funnel_vocab and funnel_answers.
-- The "Ask the funnel" page runs this same query in the browser (a test keeps the two identical).
with q as (
    select
        ' ' || trim(regexp_replace(lower({question}), '[^a-z0-9]+', ' ', 'g')) || ' ' as words,
        nullif(regexp_extract(lower({question}), '(20[0-9][0-9])', 1), '') as asked_year
),

hits as (
    select
        v.kind,
        v.target,
        row_number() over (partition by v.kind order by length(v.phrase) desc, v.target) as rank_in_kind
    from funnel_vocab as v, q
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
    from funnel_answers as a, asked as k
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
    from funnel_answers as a, asked as k, chosen as c
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
