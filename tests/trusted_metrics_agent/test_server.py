"""The MCP server starts over stdio with a fixed role, lists three tools (no SQL), answers and declines."""
import json
import sys
from pathlib import Path

import anyio

ROOT = Path(__file__).resolve().parents[2]


def call(db, role, calls):
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    async def go():
        params = StdioServerParameters(command=sys.executable, cwd=str(ROOT),
                                       args=["-m", "trusted_metrics_agent.server", "--role", role, "--db", str(db)])
        async with stdio_client(params) as (read, write), ClientSession(read, write) as s:
            await s.initialize()
            tools = (await s.list_tools()).tools
            out = [json.loads((await s.call_tool(name, args)).content[0].text) for name, args in calls]
            return {t.name: t.input_schema for t in tools}, out

    return anyio.run(go)


def test_stdio_server_answers_with_a_citation_and_declines_by_role(db):
    names, (listed, ok, declined, bad) = call(db, "people_manager", [
        ("list_metrics", {}),
        ("query_metric", {"metric": "attrition_rate_12m", "start_month": "2026-09", "group_by": ["department"]}),
        ("query_metric", {"metric": "payroll_cost", "start_month": "2026-09"}),
        ("query_metric", {"metric": "headcount", "start_month": "1999-01"}),
    ])
    assert sorted(names) == ["describe_metric", "list_metrics", "query_metric"]
    assert listed["role"] == "people_manager" and "payroll_cost" not in [m["metric"] for m in listed["metrics"]]
    assert ok["source"] == "trusted_metrics_agent/metrics.yml#attrition_rate_12m" and len(ok["rows"]) == 6
    assert "cannot see payroll_cost" in declined["declined"]
    assert "data from 2024-01" in bad["error"]


def test_no_tool_takes_a_role_and_the_start_role_holds(db):
    schemas, (res,) = call(db, "all_staff", [("query_metric", {"metric": "headcount", "start_month": "2026-09",
                                                         "group_by": ["department"]})])
    assert "cannot break headcount down by department" in res["declined"]
    for schema in schemas.values():
        assert "role" not in schema.get("properties", {})
    assert set(schemas["query_metric"]["properties"]) == {"metric", "start_month", "end_month", "group_by", "filters"}
