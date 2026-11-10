"""Query the governed metrics (dbt + MetricFlow) from Python.

Used by tests, the dashboards' data export and the AI analyst, so every number comes from one definition.
Needs a parsed dbt project (dbt/target/semantic_manifest.json) and a built warehouse.
The dbt target comes from RIDGELINE_DBT_TARGET (default duckdb); set it to snowflake to run the same
metric queries on the Snowflake build. The manifest must come from a parse for that same target.
"""
import os
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import pandas as pd

DBT_DIR = Path(__file__).resolve().parent.parent / "dbt"


@dataclass(frozen=True)
class MetricInfo:
    name: str
    label: str
    description: str
    dimensions: tuple[str, ...]


def _make_config(warehouse: str | None = None):
    os.environ.setdefault("DBT_PROFILES_DIR", str(DBT_DIR))
    from dbt_metricflow.cli.cli_configuration import CLIConfiguration

    cwd, saved = Path.cwd(), os.environ.get("RIDGELINE_DUCKDB_PATH")
    if warehouse:
        os.environ["RIDGELINE_DUCKDB_PATH"] = warehouse  # read by dbt/profiles.yml
    os.chdir(DBT_DIR)  # MetricFlow finds the dbt project from the working directory
    try:
        cfg = CLIConfiguration()
        cfg.setup()
        _ = cfg.mf  # build the engine now, while in the project directory
    finally:
        os.chdir(cwd)
        if warehouse:
            if saved is None:
                os.environ.pop("RIDGELINE_DUCKDB_PATH", None)
            else:
                os.environ["RIDGELINE_DUCKDB_PATH"] = saved
    return cfg


@lru_cache(maxsize=1)
def _config():
    return _make_config()


@lru_cache(maxsize=1)
def _compile_config():
    """MetricFlow on an empty stub with the warehouse's file name: same catalog name, so the compiled SQL
    is identical, but compiling never opens the real warehouse (dbt-duckdb always opens read-write)."""
    import duckdb

    real = Path(os.environ.get("RIDGELINE_DUCKDB_PATH", DBT_DIR.parent / "warehouse" / "ridgeline.duckdb"))
    stub = Path(tempfile.mkdtemp(prefix="ridgeline-mf-")) / real.name  # one per process: dbt locks it
    duckdb.connect(str(stub)).close()
    return _make_config(str(stub))


def list_metrics() -> list[MetricInfo]:
    """Metric names, definitions and dimensions. Read from the manifest on the stub engine, so listing
    never opens (and write-locks) the warehouse while other processes are reading it."""
    mf = _compile_config().mf
    out = []
    for m in mf.list_metrics():
        dims = tuple(sorted(d.dunder_name for d in m.dimensions))
        out.append(MetricInfo(m.name, m.label or m.name, (m.description or "").strip(), dims))
    return sorted(out, key=lambda m: m.name)


def query(metrics: list[str], group_by: list[str] | None = None, where: list[str] | None = None,
          order_by: list[str] | None = None, limit: int | None = None) -> pd.DataFrame:
    """Run a metric query; returns one column per group-by and one per metric."""
    from metricflow.engine.metricflow_engine import MetricFlowQueryRequest

    request = MetricFlowQueryRequest.create(
        metric_names=metrics, group_by_names=group_by or [], where_constraints=where,
        order_by_names=order_by, limit=limit,
    )
    table = _config().mf.query(request).result_df
    # Snowflake returns unquoted aliases upper-case; DuckDB keeps them lower-case. Same names either way.
    return pd.DataFrame(list(table.rows), columns=[c.column_name.lower() for c in table.column_descriptions])


def explain(metrics: list[str], group_by: list[str] | None = None, where: list[str] | None = None,
            order_by: list[str] | None = None, limit: int | None = None) -> str:
    """The SQL MetricFlow would run for this query. Compiling needs no warehouse connection, so the
    AI analyst can run the result on its own read-only connection."""
    from metricflow.engine.metricflow_engine import MetricFlowQueryRequest

    request = MetricFlowQueryRequest.create(metric_names=metrics, group_by_names=group_by or [],
                                            where_constraints=where, order_by_names=order_by, limit=limit)
    return _compile_config().mf.explain(request).sql_statement.sql


def target() -> str:
    return os.environ.get("RIDGELINE_DBT_TARGET", "duckdb")


def run_compiled(sql: str) -> tuple[list[str], list[list]]:
    """Run SQL from explain() on the configured warehouse through MetricFlow's own client.

    Used on Snowflake, where the AI analyst has no read-only file to open: the caller checks the SQL first
    (analyst/sql_guard.check_snowflake_sql). Column names come back lower-case, as in query().
    """
    table = _config().mf.sql_client.query(sql)
    return [c.column_name.lower() for c in table.column_descriptions], [list(r) for r in table.rows]
