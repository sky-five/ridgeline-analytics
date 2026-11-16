-- One row per month, province, product and channel from the first month to the as-of month: policies in force at
-- month end, new policies, written and earned premium, claims by loss month, renewals due and renewed.
-- Earned premium is spread over the days of the term; a month earns the days of the term that fall in it.
with months as (
    select m::date as month_start, (m + interval 1 month)::date as next_month
    from generate_series(
        date '{{ var("first_month") }}', date_trunc('month', date '{{ var("as_of") }}'), interval 1 month
    ) as s (m)
),

segments as (
    select distinct province, product, channel from {{ ref('stg_book__terms') }}
),

grid as (
    select * from months cross join segments
),

term_month as (
    select
        m.month_start,
        t.province,
        t.product,
        t.channel,
        t.written_premium
        * (least(t.end_date, m.next_month) - greatest(t.start_date, m.month_start))
        / (t.end_date - t.start_date) as earned,
        t.start_date < m.next_month and t.end_date >= m.next_month as in_force_at_end
    from {{ ref('stg_book__terms') }} as t
    inner join months as m on t.start_date < m.next_month and t.end_date > m.month_start
),

exposure as (
    select
        month_start,
        province,
        product,
        channel,
        count(*) filter (where in_force_at_end) as policies_in_force,
        sum(earned) as earned_premium
    from term_month
    group by all
),

written as (
    select
        date_trunc('month', start_date)::date as month_start,
        province,
        product,
        channel,
        count(*) filter (where term_number = 1) as new_policies,
        sum(written_premium) as written_premium
    from {{ ref('stg_book__terms') }}
    group by all
),

renewals as (
    select
        renewal_month as month_start,
        province,
        product,
        channel,
        count(*) as renewals_due,
        count(*) filter (where outcome = 'renewed') as renewed,
        sum(renewal_offer_change) as sum_rate_change
    from {{ ref('stg_book__terms') }}
    where outcome != 'not_due'
    group by all
),

losses as (
    select
        date_trunc('month', c.loss_date)::date as month_start,
        t.province,
        t.product,
        t.channel,
        count(*) as claims,
        sum(c.incurred) as incurred
    from {{ ref('stg_book__claims') }} as c
    inner join {{ ref('stg_book__terms') }} as t using (term_id)
    group by all
)

select
    g.month_start,
    g.province,
    g.product,
    g.channel,
    coalesce(e.policies_in_force, 0) as policies_in_force,
    coalesce(w.new_policies, 0) as new_policies,
    coalesce(w.written_premium, 0)::decimal(18, 2) as written_premium,
    coalesce(e.earned_premium, 0)::decimal(18, 2) as earned_premium,
    coalesce(l.claims, 0) as claims,
    coalesce(l.incurred, 0)::decimal(18, 2) as incurred,
    coalesce(r.renewals_due, 0) as renewals_due,
    coalesce(r.renewed, 0) as renewed,
    coalesce(r.sum_rate_change, 0) as sum_rate_change
from grid as g
left join exposure as e using (month_start, province, product, channel)
left join written as w using (month_start, province, product, channel)
left join renewals as r using (month_start, province, product, channel)
left join losses as l using (month_start, province, product, channel)
