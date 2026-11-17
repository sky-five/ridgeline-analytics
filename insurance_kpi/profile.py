"""Load the two exports into DuckDB, profile every column, run the data-quality checks and build the cleaned tables.

Schemas: raw (the exports as delivered), stg (row-level fixes: exact duplicate rows dropped, swapped dates put back,
sign errors flipped, a missing province set to 'unknown', test policies dropped) and clean (claims that join a policy
and fall inside its term). Every check is a SQL query that returns the key of each row it flags, so it can be scored
against the faults the simulator planted.
"""
import duckdb
import pandas as pd

from insurance_kpi.simulate import Book

LINES, PROVINCES, CHANNELS, STATUSES = ("auto", "home"), ("ON", "AB", "BC", "QC"), ("broker", "direct"), (
    "open", "closed")


def _in(values) -> str:
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


# name -> (table, what it means, what the clean step does, SQL returning the flagged keys as `key`)
CHECKS = {
    "duplicate_claim": ("claims", "claim_id appears more than once", "keep one copy (the copies are identical)",
                        "select claim_id as key from raw.claims qualify row_number() over (partition by claim_id) > 1"),
    "orphan_claim": ("claims", "policy_id is in no policy export", "drop the claim",
                     "select c.claim_id as key from stg.claims c anti join raw.policies p using (policy_id)"),
    "loss_outside_term": ("claims", "loss date before the policy started or on/after it ended", "drop the claim",
                          "select c.claim_id as key from stg.claims c join stg.policies p using (policy_id) "
                          "where c.loss_date < p.start_date or c.loss_date >= p.end_date"),
    "negative_paid": ("claims", "paid amount below zero", "flip the sign",
                      "select claim_id as key from raw.claims where paid < 0"),
    "reported_before_loss": ("claims", "reported date earlier than loss date", "swap the two dates back",
                             "select claim_id as key from raw.claims where reported_date < loss_date"),
    "missing_province": ("policies", "province is empty", "set province to 'unknown'",
                         "select policy_id as key from raw.policies where province is null"),
    "zero_premium_test_policy": ("policies", "written premium zero or below", "drop the policy",
                                 "select policy_id as key from raw.policies where written_premium <= 0"),
    # checks that pass on this export; they stay so a new fault is caught
    "duplicate_policy": ("policies", "policy_id appears more than once", "-",
                         "select policy_id as key from raw.policies "
                         "qualify row_number() over (partition by policy_id) > 1"),
    "term_not_positive": ("policies", "end date not after start date", "-",
                          "select policy_id as key from raw.policies where end_date <= start_date"),
    "unknown_code": ("policies", "line, province or channel outside the accepted values", "-",
                     f"select policy_id as key from raw.policies where line not in {_in(LINES)} "
                     f"or province not in {_in(PROVINCES)} or channel not in {_in(CHANNELS)}"),
    "commission_out_of_range": ("policies", "commission rate outside 0 to 30%", "-",
                                "select policy_id as key from raw.policies "
                                "where commission_rate not between 0 and 0.3"),
    "unknown_status": ("claims", "status not open or closed", "-",
                       f"select claim_id as key from raw.claims where status not in {_in(STATUSES)}"),
    "negative_reserve": ("claims", "case reserve below zero", "-",
                         "select claim_id as key from raw.claims where case_reserve < 0"),
    "closed_with_reserve": ("claims", "closed claim still holds a case reserve", "-",
                            "select claim_id as key from raw.claims where status = 'closed' and case_reserve <> 0"),
}

STG_SQL = """
create or replace schema stg;
create or replace table stg.policies as
select policy_id, line, coalesce(province, 'unknown') as province, channel, start_date, end_date, written_premium,
       commission_rate
from raw.policies where written_premium > 0;
create or replace table stg.claims as
select distinct claim_id, policy_id, least(loss_date, reported_date) as loss_date,
       greatest(loss_date, reported_date) as reported_date, status, abs(paid) as paid, case_reserve
from raw.claims;
create or replace schema clean;
create or replace table clean.policies as select * from stg.policies;
create or replace table clean.claims as
select c.* from stg.claims c join stg.policies p using (policy_id)
where c.loss_date >= p.start_date and c.loss_date < p.end_date;
"""


def load(con: duckdb.DuckDBPyConnection, book: Book) -> None:
    con.execute("create or replace schema raw")
    for name in ("policies", "claims"):
        df = getattr(book, name)
        con.register("df", df)
        con.execute(f"create or replace table raw.{name} as select * from df")
        con.unregister("df")
    # the exports carry dates as dates and amounts as doubles; make that explicit
    for table, col in [("policies", "start_date"), ("policies", "end_date"), ("claims", "loss_date"),
                       ("claims", "reported_date")]:
        con.execute(f"alter table raw.{table} alter {col} type date")
    con.execute(STG_SQL)


def column_profile(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """One row per raw column: type, rows, nulls, distinct values, min and max."""
    rows = []
    for table in ("policies", "claims"):
        cols = con.sql(f"select column_name, data_type from information_schema.columns "
                       f"where table_schema = 'raw' and table_name = '{table}' order by ordinal_position").fetchall()
        for col, typ in cols:
            n, nulls, distinct, lo, hi = con.sql(
                f'select count(*), count(*) - count("{col}"), count(distinct "{col}"), min("{col}")::varchar, '
                f'max("{col}")::varchar from raw.{table}').fetchone()
            rows.append((table, col, typ, n, nulls, round(nulls / n, 4), distinct, lo, hi))
    return pd.DataFrame(rows, columns=["table_name", "column_name", "data_type", "rows", "nulls", "null_share",
                                       "distinct_values", "min_value", "max_value"])


def run_checks(con: duckdb.DuckDBPyConnection) -> dict[str, list[str]]:
    return {name: sorted(k for (k,) in con.sql(sql).fetchall()) for name, (_, _, _, sql) in CHECKS.items()}


def score_checks(flagged: dict[str, list[str]], planted: pd.DataFrame) -> pd.DataFrame:
    """Rows flagged by each check against the rows planted with that fault (none planted for the passing checks)."""
    rows = []
    for name, (table, meaning, action, _) in CHECKS.items():
        truth = set(planted.loc[planted["fault"] == name, "key"])
        got = set(flagged[name])
        rows.append((name, table, meaning, action, len(flagged[name]), len(truth), len(got & truth), len(got - truth),
                     len(truth - got)))
    return pd.DataFrame(rows, columns=["check_name", "table_name", "rule", "clean_step", "rows_flagged", "planted",
                                       "caught", "false_flags", "missed"])
