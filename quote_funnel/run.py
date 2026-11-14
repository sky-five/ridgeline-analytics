"""Simulate, build the funnel marts, run the teardown and the carrier sizing; return one summary."""
from datetime import timedelta

import duckdb

from quote_funnel import carrier, counting, metrics, simulate

ONBOARDING_COST = 25_000.0  # assumed one-off cost to integrate and test a carrier; replace with the real quote


def build(con: duckdb.DuckDBPyConnection | None = None, d: dict | None = None):
    con = con or duckdb.connect()
    d = d or simulate.draws()
    simulate.load(con, simulate.simulate(d))
    metrics.build(con)
    return con, d


def run(con: duckdb.DuckDBPyConnection | None = None) -> dict:
    con, d = build(con)
    rows = {t: con.execute(f"select count(*) from source.{t}").fetchone()[0]
            for t in ("sessions", "quote_requests", "carrier_quotes", "clicks", "binds")}
    overall = con.execute("""
        select count(*) as sessions,
               count(*) filter (where quoted) / count(*) as quote_rate,
               count(*) filter (where clicked) / count(*) filter (where quoted) as click_rate,
               count(*) filter (where bound) / count(*) filter (where clicked) as bind_rate,
               count(*) filter (where bound) / count(*) filter (where quoted) as quote_to_bind,
               sum(commission) as commission
        from mart.session_funnel""").df().iloc[0].to_dict()
    segments = con.execute("select * from mart.funnel_by_segment").df().to_dict("records")
    est, true = carrier.estimate(con, d), carrier.truth(d)
    yearly = 2 * est["added_commission"]  # the history is one half-year
    return {
        "weeks": f"{simulate.START} to the week of {simulate.START + timedelta(weeks=simulate.WEEKS - 1)}",
        "source_rows": rows,
        "funnel": overall,
        "by_segment": segments,
        "definitions": metrics.DEFINITIONS,
        "counting_change": counting.teardown(con),
        "true_logging_change": str(simulate.TRACKING_CHANGE),
        "new_carrier": {
            "estimate": est,
            "truth": true,
            "onboarding_cost_assumed": ONBOARDING_COST,
            "added_commission_per_year": yearly,
            "payback_months": 12 * ONBOARDING_COST / yearly,
        },
    }


def weekly(con: duckdb.DuckDBPyConnection):
    return con.execute("select * from mart.funnel_weekly order by week").df()
