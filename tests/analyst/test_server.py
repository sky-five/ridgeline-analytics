"""The MCP server starts over stdio, lists the six tools and answers a call. Needs a built warehouse."""
import json
import sys
from pathlib import Path

import anyio
import pytest

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "warehouse" / "ridgeline.duckdb"
pytestmark = [pytest.mark.warehouse, pytest.mark.skipif(not DB.exists(), reason="build the warehouse first")]


def test_stdio_server_lists_tools_and_runs_sql():
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    async def go():
        params = StdioServerParameters(command=sys.executable, args=["-m", "analyst.server"], cwd=str(ROOT))
        async with stdio_client(params) as (read, write), ClientSession(read, write) as s:
            await s.initialize()
            names = sorted(t.name for t in (await s.list_tools()).tools)
            ok = await s.call_tool("run_sql", {"sql": "select count(*) as n from fct_mrr_daily"})
            bad = await s.call_tool("run_sql", {"sql": "drop table fct_mrr_daily"})
            return names, ok.content[0].text, bad.content[0].text

    names, ok, bad = anyio.run(go)
    assert names == ["describe_model", "get_lineage", "list_metrics", "query_metric", "run_sql", "search_catalog"]
    assert json.loads(ok)["rows"][0][0] > 0
    assert "only SELECT" in json.loads(bad)["error"]
