"""MCP server (stdio) exposing one arm of the raw-vs-governed eval.

    python -m semantic_eval.server raw         # list_raw_tables, run_raw_sql
    python -m semantic_eval.server governed    # list_governed_metrics, query_governed_metric
"""
import sys

from mcp.server.mcpserver import MCPServer

from semantic_eval.arms import ARMS, SYSTEM, TOOLS


def make_server(arm: str) -> MCPServer:
    if arm not in ARMS:
        raise SystemExit(f"arm must be one of {ARMS}")
    server = MCPServer(name="ridgeline", instructions=SYSTEM[arm].split("End your reply")[0].strip())
    for fn in TOOLS[arm]:
        server.add_tool(fn, structured_output=False)
    return server


def main() -> None:
    make_server(sys.argv[1] if len(sys.argv) > 1 else "").run("stdio")


if __name__ == "__main__":
    main()
