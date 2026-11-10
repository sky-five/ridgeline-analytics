"""The two tool sets the analyst gets in the raw-vs-governed eval.

raw       list_raw_tables + run_raw_sql: SQL on the tables exactly as the loaders landed them
          (raw_app_db.accounts, raw_crm.crm_deals, ...). No dbt models, no metric definitions.
governed  list_governed_metrics + query_governed_metric: MetricFlow only. No SQL at all.

Both arms run on the same read-only connection and SQL guard as the analyst (analyst/sql_guard.py).
The raw arm connects to a separate file that holds only the raw tables (build_raw_copy).
With RIDGELINE_DBT_TARGET=snowflake the governed arm runs its compiled metric queries on the Snowflake
build instead, after the same one-SELECT check (sql_guard.check_snowflake_sql).
"""
import os
import tempfile
from functools import lru_cache
from pathlib import Path

import duckdb

from analyst import sql_guard

RAW_SCHEMAS = ("raw_ads", "raw_app_db", "raw_contractor_ops", "raw_crm", "raw_product_events", "raw_support")
ARMS = ("raw", "governed")


def build_raw_copy(warehouse: Path | str, dest: Path | str) -> Path:
    """Copy the loaded raw tables (dlt bookkeeping left out) into their own DuckDB file.

    The raw arm only ever connects to this file, so marts, staging views and metric tables are not
    there to find: no table-name filter to get around (DuckDB's query() and catalog functions included).
    """
    dest = Path(dest)
    dest.unlink(missing_ok=True)
    with duckdb.connect(str(dest)) as con:
        con.execute(f"attach '{Path(warehouse).as_posix()}' as wh (read_only)")
        tables = con.execute(
            "select schema_name, table_name from duckdb_tables() where database_name = 'wh' "
            f"and schema_name in {RAW_SCHEMAS} and not starts_with(table_name, '_dlt') order by 1, 2").fetchall()
        for schema, table in tables:
            con.execute(f"create schema if not exists {schema}")
            con.execute(f"create table {schema}.{table} as "
                        f"select columns(c -> not starts_with(c, '_dlt')) from wh.{schema}.{table}")
        con.execute("detach wh")
    return dest


def _warehouse() -> Path:
    return Path(os.environ.get("RIDGELINE_DUCKDB_PATH", sql_guard.DEFAULT_DB))


@lru_cache(maxsize=1)
def _raw_con():
    path = os.environ.get("RIDGELINE_RAW_DUCKDB_PATH")
    if not path:
        path = build_raw_copy(_warehouse(), Path(tempfile.mkdtemp(prefix="ridgeline-raw-")) / "raw.duckdb")
    return sql_guard.connect(path)


@lru_cache(maxsize=1)
def _con():
    return sql_guard.connect(_warehouse())


def close() -> None:
    for cached in (_raw_con, _con):
        if cached.cache_info().currsize:
            cached().close()
            cached.cache_clear()


def _error(e: Exception) -> dict:
    return {"error": f"{type(e).__name__}: {e}"}


# ---- raw arm

def list_raw_tables() -> dict:
    """Every loaded raw table (schema.table) with its columns and types. dlt bookkeeping columns are left out."""
    rows = _raw_con().execute(
        "select table_schema || '.' || table_name, column_name, data_type from information_schema.columns "
        "order by 1, ordinal_position").fetchall()
    tables: dict[str, list[str]] = {}
    for table, col, typ in rows:
        tables.setdefault(table, []).append(f"{col} {typ}")
    return {"tables": [{"table": t, "columns": cols} for t, cols in tables.items()]}


def run_raw_sql(sql: str) -> dict:
    """Run one read-only SELECT (DuckDB SQL) on the raw tables; name them as schema.table. At most 200 rows."""
    try:
        return sql_guard.run_sql(_raw_con(), sql).as_dict()
    except Exception as e:  # the agent reads the message and corrects its query
        return _error(e)


# ---- governed arm

def list_governed_metrics() -> dict:
    """The governed metrics: name, label, definition and the dimensions each can be grouped or filtered by."""
    from semantic import list_metrics

    return {"metrics": [{"name": m.name, "label": m.label, "description": m.description,
                         "dimensions": list(m.dimensions)} for m in list_metrics()]}


def query_governed_metric(metrics: list[str], group_by: list[str] | None = None, where: list[str] | None = None,
                          order_by: list[str] | None = None, limit: int | None = None) -> dict:
    """Query governed metrics through MetricFlow. group_by takes dimension names from list_governed_metrics, or
    metric_time__day/week/month/quarter/year; where takes Jinja filters, e.g.
    "{{ TimeDimension('metric_time', 'day') }} >= '2026-01-01'" or "{{ Dimension('account__channel') }} = 'seo'"."""
    from semantic import explain, run_compiled, target

    try:
        sql = explain(metrics, group_by or [], where or None, order_by or None, limit)
        if target() == "snowflake":  # same compiled metric query, run on the Snowflake build
            columns, rows = run_compiled(sql_guard.check_snowflake_sql(sql))
            rows, truncated = sql_guard.plain_rows(rows)
            return sql_guard.QueryResult(columns, rows, truncated).as_dict()
        return sql_guard.run_sql(_con(), sql).as_dict()
    except Exception as e:  # MetricFlow raises many types; the agent needs the message to fix its call
        return _error(e)


TOOLS = {"raw": [list_raw_tables, run_raw_sql], "governed": [list_governed_metrics, query_governed_metric]}

_COMMON = """You are the analyst on call for Ridgeline, a SaaS company selling software to roofing contractors. \
All data is synthetic. Answer the question with the tools you have.

- {how}
- If the data cannot answer the question, say so; never estimate or invent a number.
- Ratios are fractions between 0 and 1. Money is in USD. "Now" means the last day in the data.

End your reply with one fenced json block, and nothing after it:
```json
{{"answer": <number, text, or null if the data can't answer it>,
 "unit": "<usd | count | ratio | minutes | text>",
 "definition": "<one short sentence: how you defined the number>"}}
```"""

SYSTEM = {
    "raw": _COMMON.format(how="You have the tables as they were loaded from the source systems (app database, "
                          "CRM, ads, product events, support, contractor ops). Call list_raw_tables, then write "
                          "SQL with run_raw_sql. Choose definitions the way a careful analyst would."),
    "governed": _COMMON.format(how="You have the company's governed metrics only. Call list_governed_metrics, "
                               "pick the metric that matches the question, and query it with "
                               "query_governed_metric."),
}
