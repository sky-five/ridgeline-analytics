-- A term fully inside the covered months earns exactly its written premium (to a cent per month of rounding);
-- no term earns more.
with earned as (
    select
        t.term_id,
        t.written_premium,
        t.start_date,
        t.end_date,
        sum(
            t.written_premium
            * (least(t.end_date, (m.m + interval 1 month)::date) - greatest(t.start_date, m.m::date))
            / (t.end_date - t.start_date)
        ) as earned
    from {{ ref('stg_book__terms') }} as t
    inner join generate_series(date '{{ var("first_month") }}', date '2027-12-01', interval 1 month) as m (m)
        on t.start_date < (m.m + interval 1 month)::date and t.end_date > m.m::date
    group by all
)

select * from earned
where earned > written_premium + 0.01
    or (start_date >= date '{{ var("first_month") }}' and abs(earned - written_premium) > 0.01)
