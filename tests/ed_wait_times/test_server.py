"""The MCP server starts over stdio, lists two tools (no SQL), answers last week as the committed results do,
answers another week and patient group as breaches() does, refuses bad input by name, and cannot write."""
import json
import sys
from datetime import date

import anyio
import duckdb
import pytest

from ed_wait_times.breaches import breaches
from ed_wait_times.run import SUMMARY
from ed_wait_times.server import EdTools

ROOT = SUMMARY.parents[2]


def call(db, calls):
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    async def go():
        params = StdioServerParameters(command=sys.executable, cwd=str(ROOT),
                                       args=["-m", "ed_wait_times.server", "--db", str(db)])
        async with stdio_client(params) as (read, write), ClientSession(read, write) as s:
            await s.initialize()
            tools = (await s.list_tools()).tools
            out = [json.loads((await s.call_tool(name, args)).content[0].text) for name, args in calls]
            return {t.name: t.input_schema for t in tools}, out

    return anyio.run(go)


def test_stdio_server_answers_last_week_and_any_week(db):
    schemas, (weeks, last, other, bad_week, bad_group) = call(db, [
        ("list_weeks", {}),
        ("site_breaches", {}),
        ("site_breaches", {"week_start": "2026-10-29", "patient_group": "admitted"}),
        ("site_breaches", {"week_start": "2025-12-31"}),
        ("site_breaches", {"patient_group": "children"}),
    ])
    assert set(schemas) == {"list_weeks", "site_breaches"}
    assert set(schemas["site_breaches"]["properties"]) == {"week_start", "patient_group"}
    assert (weeks["first_week"], weeks["last_full_week"]) == ("2026-01-05", "2026-11-02")
    assert {g["patient_group"]: g["target_hours"] for g in weeks["patient_groups"]} == {
        "admitted": 8, "high_urgency_sent_home": 8, "low_urgency_sent_home": 4}
    assert len(weeks["sites"]) == 10
    # no arguments: the last full week, admitted patients, exactly as the committed results say
    assert last == json.loads(SUMMARY.read_text(encoding="utf-8"))["last_week"]
    assert last["breached"] == ["ED07", "ED03", "ED06"] and last["not_reported"] == ["ED10"]
    # a Thursday picks its week; the week ED07's beds closed in
    assert (other["week_start"], other["week_end"]) == ("2026-10-26", "2026-11-01")
    assert other["breached"] == ["ED07", "ED03"]
    assert "weeks run from 2026-01-05 to 2026-11-02" in bad_week["error"]
    assert "use one of admitted, high_urgency_sent_home, low_urgency_sent_home" in bad_group["error"]


def test_tools_match_breaches_for_every_group(db):
    tools = EdTools(db)
    with duckdb.connect(str(db), read_only=True) as con:
        for group in ("admitted", "high_urgency_sent_home", "low_urgency_sent_home"):
            for week in ("2026-01-05", "2026-06-15", "2026-11-02"):
                assert tools.site_breaches(week, group) == breaches(con, date.fromisoformat(week), group)
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        tools.site_breaches("last week")


def test_the_warehouse_is_opened_read_only(db, tmp_path):
    with EdTools(db)._con() as con, pytest.raises(duckdb.Error):
        con.execute("create table scratch (a int)")
    with pytest.raises(FileNotFoundError, match="run python -m ed_wait_times"):
        EdTools(tmp_path / "missing.duckdb")
