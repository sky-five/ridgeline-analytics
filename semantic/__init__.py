"""Query the governed metrics (dbt + MetricFlow) from Python.

Used by tests, the dashboards' data export and the AI analyst, so every number comes from one definition.
Needs a parsed dbt project (dbt/target/semantic_manifest.json) and a built warehouse.
"""
import os
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


@lru_cache(maxsize=1)
def _config():
    os.environ.setdefault("DBT_PROFILES_DIR", str(DBT_DIR))
    from dbt_metricflow.cli.cli_configuration import CLIConfiguration

    cwd = Path.cwd()
    os.chdir(DBT_DIR)  # MetricFlow finds the dbt project from the working directory
    try:
        cfg = CLIConfiguration()
        cfg.setup()
        _ = cfg.mf  # build the engine now, while in the project directory
    finally:
        os.chdir(cwd)
    return cfg


def list_metrics() -> list[MetricInfo]:
    mf = _config().mf
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
    return pd.DataFrame(list(table.rows), columns=[c.column_name for c in table.column_descriptions])


def explain(metrics: list[str], group_by: list[str] | None = None, where: list[str] | None = None) -> str:
    """The SQL MetricFlow would run for this query."""
    from metricflow.engine.metricflow_engine import MetricFlowQueryRequest

    request = MetricFlowQueryRequest.create(metric_names=metrics, group_by_names=group_by or [],
                                            where_constraints=where)
    return _config().mf.explain(request).sql_statement.sql
