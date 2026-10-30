"""The six tools an analyst agent gets. Plain functions returning JSON-ready dicts, so the MCP
server and the Claude API agent expose exactly the same behaviour.

Every number goes through the SQL guard: metric queries are compiled by MetricFlow (one governed
definition per metric) and the compiled SQL runs on the same read-only connection as ad hoc SQL.
"""
import os
from functools import lru_cache
from pathlib import Path

from analyst import sql_guard
from analyst.catalog import TARGET, Catalog


@lru_cache(maxsize=1)
def _catalog() -> Catalog:
    return Catalog.load(Path(os.environ.get("RIDGELINE_DBT_TARGET", TARGET)))


@lru_cache(maxsize=1)
def _con():
    return sql_guard.connect(os.environ.get("RIDGELINE_DUCKDB_PATH", sql_guard.DEFAULT_DB))


def _error(e: Exception) -> dict:
    return {"error": f"{type(e).__name__}: {e}"}


def search_catalog(query: str) -> dict:
    """Find marts, models and governed metrics related to a question. Start here."""
    hits = _catalog().search(query)
    return {"results": hits} if hits else {"results": [], "hint": "try other words, or list_metrics"}


def describe_model(name: str) -> dict:
    """Columns, grain description, tests, contract and direct parents/children of one model."""
    try:
        return _catalog().describe(name)
    except KeyError as e:
        return _error(e)


def get_lineage(name: str, direction: str = "upstream") -> dict:
    """Every model and source a model is built from (upstream) or feeds (downstream)."""
    try:
        return {"model": name, "direction": direction, "nodes": _catalog().lineage(name, direction)}
    except (KeyError, ValueError) as e:
        return _error(e)


def list_metrics() -> dict:
    """The governed metrics (MetricFlow): name, definition and the mart each is built on."""
    return {"metrics": _catalog().metrics()}


def query_metric(metrics: list[str], group_by: list[str] | None = None, where: list[str] | None = None,
                 order_by: list[str] | None = None, limit: int | None = None) -> dict:
    """Query governed metrics. group_by uses MetricFlow names, e.g. metric_time__month,
    account__plan; where uses Jinja filters, e.g. "{{ TimeDimension('metric_time', 'day') }} >= '2026-01-01'"."""
    try:
        sql = _compile_metric_sql(tuple(metrics), tuple(group_by or ()), tuple(where or ()),
                                  tuple(order_by or ()), limit)
        result = sql_guard.run_sql(_con(), sql).as_dict()
        return {"compiled_sql": sql, **result}
    except Exception as e:  # MetricFlow raises many types; the agent needs the message to fix its call
        return _error(e)


def run_sql(sql: str) -> dict:
    """Run one read-only SELECT on the warehouse (DuckDB SQL). Prefer marts (fct_/dim_) over staging."""
    try:
        return sql_guard.run_sql(_con(), sql).as_dict()
    except Exception as e:  # unsafe SQL, timeouts, DuckDB binder errors: the agent reads them and corrects
        return _error(e)


@lru_cache(maxsize=256)
def _compile_metric_sql(metrics, group_by, where, order_by, limit) -> str:
    from semantic import explain

    return explain(list(metrics), list(group_by), list(where) or None, list(order_by) or None, limit)


def close() -> None:
    """Release the read-only connection (DuckDB allows one connection config per file per process)."""
    if _con.cache_info().currsize:
        _con().close()
        _con.cache_clear()


ALL = [search_catalog, describe_model, get_lineage, list_metrics, query_metric, run_sql]
