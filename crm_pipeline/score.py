"""Score the warehouse's data fixes against the pack's labels, and summarise the marts.

The labels never enter the warehouse; they come from build_sales_crm_history(), which keeps them.
"""
import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

import duckdb

from pipelines.engine import build_sales_crm_history

RESULTS = Path(__file__).resolve().parent / "results" / "summary.json"


@dataclass
class Summary:
    as_of: str
    account_records: int
    companies_after_dedupe: int
    duplicates_labelled: int
    duplicates_found: int
    duplicates_false_matches: int
    backdated_labelled_closed: int
    backdated_found: int
    backdated_false_flags: int
    won_usd_moved_to_true_quarter: float
    forecast_quarters: int
    forecast_mape_crm_probability: float
    forecast_mape_learned_rates: float
    coverage_next_quarter: float

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)


def score(as_of: date, db_path: Path) -> Summary:
    labels = build_sales_crm_history()
    with duckdb.connect(str(db_path), read_only=True) as con:
        con.register("acct_labels", labels["accounts"][["account_id", "duplicate_of_account_id"]])
        con.register("opp_labels", labels["opportunities"][["opportunity_id", "close_date_backdated"]])

        def one(sql: str, params=None):
            return con.execute(sql, params).fetchone()

        records, companies = one("select count(*), count(distinct canonical_account_id) from int_account_dedupe")
        # a found duplicate must point at the same original the label names
        dup_labelled, dup_found, dup_false = one("""
            select
                count(*) filter (where l.duplicate_of_account_id is not null),
                count(*) filter (where d.canonical_account_id = l.duplicate_of_account_id),
                count(*) filter (where d.matched_on is not null
                                 and d.canonical_account_id is distinct from l.duplicate_of_account_id)
            from int_account_dedupe as d inner join acct_labels as l using (account_id)""")
        # a deal still open on the as-of date has not been backdated yet, whatever its label says later
        bd_labelled, bd_found, bd_false = one("""
            select
                count(*) filter (where l.close_date_backdated),
                count(*) filter (where c.is_backdated and l.close_date_backdated),
                count(*) filter (where c.is_backdated and not l.close_date_backdated)
            from int_opportunity_close_dates as c
            inner join opp_labels as l using (opportunity_id)
            where c.closed_on is not null""")
        (moved,) = one("""
            select coalesce(sum(o.amount_usd), 0) from fct_opportunities as o where o.is_backdated and o.is_won""")
        n_q, mape_crm, mape_learned = one("""
            select count(*), avg(abs(error_crm_probability)) filter (where error_learned_rates is not null),
                   avg(abs(error_learned_rates))
            from forecast_backtest""")
        (coverage,) = one("""
            select coverage_ratio from pipeline_coverage
            where close_quarter = date_trunc('quarter', ?::date + interval 1 day)""", [as_of])
    return Summary(
        as_of=as_of.isoformat(), account_records=records, companies_after_dedupe=companies,
        duplicates_labelled=dup_labelled, duplicates_found=dup_found, duplicates_false_matches=dup_false,
        backdated_labelled_closed=bd_labelled, backdated_found=bd_found, backdated_false_flags=bd_false,
        won_usd_moved_to_true_quarter=float(moved), forecast_quarters=n_q,
        forecast_mape_crm_probability=round(mape_crm, 3), forecast_mape_learned_rates=round(mape_learned, 3),
        coverage_next_quarter=float(coverage) if coverage is not None else float("nan"),
    )
