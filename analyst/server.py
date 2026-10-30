"""MCP server for the analyst tools (stdio). Works with Claude Code, Claude Desktop or any MCP client.

    claude mcp add ridgeline -- .venv/Scripts/python -m analyst.server      (macOS/Linux: .venv/bin/python)

Read-only by construction: see analyst/sql_guard.py.
"""
from mcp.server.mcpserver import MCPServer

from analyst import tools
from analyst.prompt import SYSTEM

server = MCPServer(
    name="ridgeline",
    instructions=SYSTEM.split("End your reply")[0].strip(),
)
for fn in tools.ALL:
    server.add_tool(fn, structured_output=False)


def main() -> None:
    server.run("stdio")


if __name__ == "__main__":
    main()
