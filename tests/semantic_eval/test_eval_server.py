"""Each arm's MCP server starts over stdio and exposes only that arm's tools. Needs a built warehouse."""
import json
import os
import shutil
import sys
from pathlib import Path

import anyio
import pytest

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "warehouse" / "ridgeline.duckdb"
pytestmark = [pytest.mark.warehouse, pytest.mark.skipif(not DB.exists(), reason="build the warehouse first")]


@pytest.fixture(scope="module")
def warehouse_copy(tmp_path_factory):
    """Earlier tests in this process may hold the warehouse's write lock (dbt-duckdb keeps it), so the
    servers read a copy."""
    path = tmp_path_factory.mktemp("wh") / DB.name
    shutil.copy(DB, path)
    return path


def _session(db: Path, arm: str, call: str, args: dict):
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    async def go():
        params = StdioServerParameters(command=sys.executable, args=["-m", "semantic_eval.server", arm],
                                        cwd=str(ROOT), env={**os.environ, "RIDGELINE_DUCKDB_PATH": str(db)})
        async with stdio_client(params) as (read, write), ClientSession(read, write) as s:
            await s.initialize()
            names = sorted(t.name for t in (await s.list_tools()).tools)
            res = await s.call_tool(call, args)
            return names, json.loads(res.content[0].text)

    return anyio.run(go)


def test_raw_server(warehouse_copy):
    names, res = _session(warehouse_copy, "raw", "run_raw_sql", {"sql": "select count(*) from raw_app_db.accounts"})
    assert names == ["list_raw_tables", "run_raw_sql"]
    assert res["rows"][0][0] > 0


def test_governed_server(warehouse_copy):
    names, res = _session(warehouse_copy, "governed", "query_governed_metric", {"metrics": ["paying_accounts"]})
    assert names == ["list_governed_metrics", "query_governed_metric"]
    assert res["rows"][0][-1] > 0
