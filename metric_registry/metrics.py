"""Query this folder's MetricFlow semantic layer from Python.

Needs a built warehouse and dbt/target/semantic_manifest.json (both written by load.dbt_build).
"""
import os
from functools import lru_cache
from pathlib import Path

import pandas as pd

from metric_registry.load import DB_ENV, DBT_DIR, DEFAULT_DB

HEADLINE = ["units_sold", "average_transaction_price", "incentive_per_unit", "incentive_share_of_msrp",
            "incentive_penetration"]
SLICES = ["vehicle__segment", "dealer__region", "sale__finance_type"]


@lru_cache(maxsize=4)
def _engine(db: str):
    from dbt_metricflow.cli.cli_configuration import CLIConfiguration

    saved = os.environ.get(DB_ENV)
    os.environ[DB_ENV] = db  # dbt/profiles.yml reads it when MetricFlow opens the connection
    try:
        cfg = CLIConfiguration()
        cfg.setup(dbt_profiles_path=DBT_DIR, dbt_project_path=DBT_DIR)
        return cfg.mf
    finally:
        if saved is None:
            os.environ.pop(DB_ENV, None)
        else:
            os.environ[DB_ENV] = saved


def query(metrics: list[str], group_by: list[str] | None = None, where: list[str] | None = None,
          db: Path = DEFAULT_DB) -> pd.DataFrame:
    """One column per group-by and one per metric, ordered by the group-bys."""
    from metricflow.engine.metricflow_engine import MetricFlowQueryRequest

    group_by = group_by or []
    request = MetricFlowQueryRequest.create(metric_names=metrics, group_by_names=group_by,
                                            where_constraints=where, order_by_names=group_by)
    table = _engine(str(Path(db).resolve())).query(request).result_df
    return pd.DataFrame(list(table.rows), columns=[c.column_name.lower() for c in table.column_descriptions])


def explain(metrics: list[str], group_by: list[str] | None = None, where: list[str] | None = None,
                  db: Path = DEFAULT_DB) -> str:
    """The SQL MetricFlow runs for exactly this query, filters included: the lineage of an answer."""
    from metricflow.engine.metricflow_engine import MetricFlowQueryRequest

    group_by = group_by or []
    request = MetricFlowQueryRequest.create(metric_names=metrics, group_by_names=group_by,
                                            where_constraints=where, order_by_names=group_by)
    return _engine(str(Path(db).resolve())).explain(request).sql_statement.sql


def list_metrics(db: Path = DEFAULT_DB) -> list[dict]:
    """Every metric with its label, description and the dimensions it can be grouped by."""
    out = []
    for m in _engine(str(Path(db).resolve())).list_metrics():
        out.append({"name": m.name, "label": m.label or m.name, "description": " ".join((m.description or "").split()),
                    "version": m.config.meta.get("version"), "owner": m.config.meta.get("owner"),
                    "dimensions": sorted(d.dunder_name for d in m.dimensions)})
    return sorted(out, key=lambda m: m["name"])
