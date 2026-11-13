"""Read-only MCP server (stdio) for the governed HR and payroll metrics. The role is set when it starts:

    claude mcp add hr-metrics -- .venv/bin/python -m trusted_metrics_agent.server --role people_manager

Three tools: list_metrics, describe_metric, query_metric. There is no SQL tool, and no tool takes a role,
so a client (or a model) can only ask for what that role may see. Build the warehouse first:
python -m trusted_metrics_agent.
"""
import argparse
import os
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from trusted_metrics_agent.load import DEFAULT_DB
from trusted_metrics_agent.metrics import Declined, MetricStore

INSTRUCTIONS = (
    "Governed HR and payroll metrics (synthetic data). Answer only from query_metric results, name the "
    "metric definition (source) behind each number, and when a tool declines, say the role cannot see it."
)


def build(role: str, db_path: Path = DEFAULT_DB) -> MCPServer:
    store = MetricStore.open(role, db_path)

    def guarded(fn, *args, **kwargs) -> dict:
        try:
            return fn(*args, **kwargs)
        except Declined as e:
            return {"declined": str(e), "role": role}
        except ValueError as e:
            return {"error": str(e)}

    def list_metrics() -> dict:
        """The metrics your role can query, the breakdowns it may use, and the months with data. Start here."""
        return guarded(store.list_metrics)

    def describe_metric(metric: str) -> dict:
        """The governed definition of one metric (formula, owner, version) and whether your role may query it."""
        return guarded(store.describe_metric, metric)

    def query_metric(metric: str, start_month: str, end_month: str | None = None,
                     group_by: list[str] | None = None, filters: dict[str, str] | None = None) -> dict:
        """Values of one governed metric. Months are YYYY-MM (end_month defaults to start_month). group_by and
        filters use department, location or job_level, as far as your role allows. Each result names the
        definition it came from (source, version); pay values for groups under 5 people are withheld."""
        return guarded(store.query_metric, metric, start_month, end_month, group_by, filters)

    server = MCPServer(name="hr-metrics", instructions=f"{INSTRUCTIONS} Role: {role}.")
    for fn in (list_metrics, describe_metric, query_metric):
        server.add_tool(fn, structured_output=False)
    return server


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m trusted_metrics_agent.server")
    p.add_argument("--role", default=os.environ.get("TRUSTED_METRICS_ROLE", "all_staff"))
    p.add_argument("--db", type=Path, default=Path(os.environ.get("TRUSTED_METRICS_DUCKDB_PATH", DEFAULT_DB)))
    args = p.parse_args()
    build(args.role, args.db).run("stdio")


if __name__ == "__main__":
    main()
