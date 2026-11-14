"""Funnel metrics in DuckDB SQL, built from the source tables in simulate.py.

The unit is the shopping session. A session is quoted when at least one carrier returned a price, clicked when
the shopper clicked through to a carrier, and bound when that carrier reported a policy. Every rate below is
sessions over sessions, so a change in how many form submits get logged cannot move it.

`quote_to_bind_per_request` is the version the old dashboard used: binds over quoted requests. It is kept so
the teardown can show what it does when the request log changes.
"""
import duckdb

DEFINITIONS = {
    "sessions": "Shopping sessions with at least one logged quote request.",
    "quote_rate": "Quoted sessions / sessions. Quoted = at least one carrier returned a price.",
    "click_rate": "Sessions that clicked through to a carrier / quoted sessions.",
    "bind_rate": "Bound sessions / clicked sessions. Bound = the carrier reported a policy for the session.",
    "quote_to_bind": "Bound sessions / quoted sessions. The headline conversion rate.",
    "commission_per_session": "Commission earned on binds / sessions.",
    "quote_to_bind_per_request": "Binds / quote requests in quoted sessions. Old dashboard version; moves when "
                                 "the request log changes. Do not use.",
    "requests_per_session": "Logged quote requests / sessions. A logging health check, not a shopper metric.",
}

SQL = """
create schema if not exists mart;

create or replace table mart.session_funnel as
with requests as (
    select session_id, count(*) as n_requests from source.quote_requests group by 1
), quotes as (
    select session_id, count(*) as n_quotes, min(premium) as best_premium from source.carrier_quotes group by 1
)
select
    s.session_id,
    cast(date_trunc('week', s.started_at) as date) as week,
    s.line, s.tier, s.line || '_' || s.tier as segment, s.device,
    r.n_requests,
    coalesce(q.n_quotes, 0) as n_quotes,
    q.best_premium,
    q.session_id is not null as quoted,
    c.session_id is not null as clicked,
    b.session_id is not null as bound,
    c.carrier_id as clicked_carrier,
    b.carrier_id as bound_carrier,
    coalesce(k.commission_per_bind, 0) as commission
from source.sessions s
join requests r using (session_id)
left join quotes q using (session_id)
left join source.clicks c using (session_id)
left join source.binds b using (session_id)
left join source.carriers k on k.carrier_id = b.carrier_id;

create or replace table mart.funnel_weekly as
select
    week,
    count(*) as sessions,
    sum(n_requests) as requests,
    count(*) filter (where quoted) as quoted_sessions,
    sum(n_requests) filter (where quoted) as quoted_requests,
    count(*) filter (where clicked) as clicked_sessions,
    count(*) filter (where bound) as bound_sessions,
    sum(commission) as commission,
    count(*) filter (where quoted) / count(*) as quote_rate,
    count(*) filter (where clicked) / count(*) filter (where quoted) as click_rate,
    count(*) filter (where bound) / count(*) filter (where clicked) as bind_rate,
    count(*) filter (where bound) / count(*) filter (where quoted) as quote_to_bind,
    sum(commission) / count(*) as commission_per_session,
    count(*) filter (where bound) / sum(n_requests) filter (where quoted) as quote_to_bind_per_request,
    sum(n_requests) / count(*) as requests_per_session
from mart.session_funnel
group by 1
order by 1;

create or replace table mart.funnel_by_segment as
select
    segment,
    count(*) as sessions,
    avg(n_quotes) as quotes_per_session,
    count(*) filter (where quoted) / count(*) as quote_rate,
    count(*) filter (where clicked) / count(*) filter (where quoted) as click_rate,
    count(*) filter (where bound) / count(*) filter (where clicked) as bind_rate,
    count(*) filter (where bound) / count(*) filter (where quoted) as quote_to_bind,
    count(*) filter (where bound) as bound_sessions,
    sum(commission) as commission
from mart.session_funnel
group by 1
order by 1;
"""


def build(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(SQL)
