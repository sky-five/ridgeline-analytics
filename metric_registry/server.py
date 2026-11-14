"""Read-only MCP server (stdio) over the metric registry's semantic layer.

    claude mcp add vehicle-metrics -- .venv/bin/python -m metric_registry.server

Three tools: list_metrics, explain_metric, query_metrics. There is no SQL tool: a query names registry
metrics, group-bys and filters, and each result carries the SQL MetricFlow ran for it, so every number can
be traced to its tables. Build the warehouse first: python -m metric_registry.
"""
import argparse
import os
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from metric_registry.load import DB_ENV, DEFAULT_DB
from metric_registry.tools import SemanticTools

INSTRUCTIONS = (
    "Governed vehicle-sales and incentive metrics (synthetic data, 2025-01-01 to 2026-06-30). Answer only "
    "from query_metrics results, name the metric behind each number, and refuse what no metric answers."
)


def build(db_path: Path = DEFAULT_DB) -> MCPServer:
    tools = SemanticTools(db_path)

    def guarded(fn, *args, **kwargs) -> dict:
        try:
            return fn(*args, **kwargs)
        except ValueError as e:
            return {"error": str(e)}

    def list_metrics() -> dict:
        """Every governed metric (name, label, definition, version, owner, the group-bys it allows), the
        values each filter dimension takes, and the first and last day with data. Start here."""
        return guarded(tools.list_metrics)

    def explain_metric(metric: str) -> dict:
        """The registry entry behind one metric: definition, how it is computed, version, owner, changelog,
        fingerprint, the group-bys it allows and the glossary terms it uses."""
        return guarded(tools.explain_metric, metric)

    def query_metrics(metrics: list[str], group_by: list[str] | None = None, filters: dict[str, str] | None = None,
                      start_date: str | None = None, end_date: str | None = None) -> dict:
        """Values of one or more governed metrics, and the SQL MetricFlow ran for them. group_by takes
        metric_time__month, metric_time__quarter, metric_time__year or a dimension (vehicle__segment, ...).
        filters is {dimension: value} with values from list_metrics, e.g. {"vehicle__segment": "ev"}.
        start_date and end_date (YYYY-MM-DD, both included) limit the sale days."""
        return guarded(tools.query_metrics, metrics, group_by, filters, start_date, end_date)

    server = MCPServer(name="vehicle-metrics", instructions=INSTRUCTIONS)
    for fn in (list_metrics, explain_metric, query_metrics):
        server.add_tool(fn, structured_output=False)
    return server


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m metric_registry.server")
    p.add_argument("--db", type=Path, default=Path(os.environ.get(DB_ENV, DEFAULT_DB)))
    args = p.parse_args()
    build(args.db).run("stdio")


if __name__ == "__main__":
    main()
