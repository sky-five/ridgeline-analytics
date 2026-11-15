"""Read-only MCP server (stdio) over the ED wait-times marts.

    claude mcp add ed-wait-times -- .venv/bin/python -m ed_wait_times.server

Two tools: list_weeks and site_breaches. There is no SQL tool: site_breaches calls breaches() on the site_week
mart, and the warehouse is opened read-only for every call. Build the warehouse first: python -m ed_wait_times.
"""
import argparse
import os
from datetime import date, timedelta
from pathlib import Path

import duckdb
from mcp.server.mcpserver import MCPServer

from ed_wait_times.breaches import GROUP, breaches, last_full_week
from ed_wait_times.load import DB_ENV, DEFAULT_DB

INSTRUCTIONS = (
    "Emergency-department wait times for ten simulated hospital sites (ED01 to ED10, not real hospitals), weekly, "
    "2026-01-05 to 2026-11-08. A site breaches when the 90th percentile of its patients' hours in the ED that week "
    "is over the target; a site under 20 patients is 'not reported', never passing. Answer only from tool results."
)


class EdTools:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            raise FileNotFoundError(f"{self.db_path} not found: run python -m ed_wait_times first")

    def _con(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(str(self.db_path), read_only=True)

    def list_weeks(self) -> dict:
        with self._con() as con:
            first, last = con.sql("select min(week_start), max(week_start) from site_week").fetchone()
            groups = con.sql("""select patient_group, any_value(target_hours) as target_hours from site_week
                                group by 1 order by 1""").fetchall()
            sites = con.sql("select site_id, site_type, region from dim_sites order by 1").fetchall()
            latest = last_full_week(con)
        return {
            "first_week": first.isoformat(), "last_week": last.isoformat(), "last_full_week": latest.isoformat(),
            "weeks_start_on": "Monday",
            "patient_groups": [{"patient_group": g, "target_hours": int(t)} for g, t in groups],
            "sites": [{"site_id": s, "site_type": t, "region": r} for s, t, r in sites],
        }

    def site_breaches(self, week_start: str | None = None, patient_group: str = GROUP) -> dict:
        with self._con() as con:
            groups = [r[0] for r in con.sql("select distinct patient_group from site_week order by 1").fetchall()]
            if patient_group not in groups:
                raise ValueError(f"unknown patient_group {patient_group!r}; use one of {', '.join(groups)}")
            week = None
            if week_start:
                try:
                    day = date.fromisoformat(week_start)
                except ValueError:
                    raise ValueError(f"week_start must be YYYY-MM-DD, got {week_start!r}") from None
                week = day - timedelta(days=day.weekday())  # any day picks the week (Monday to Sunday) it falls in
                first, last = con.sql("select min(week_start), max(week_start) from site_week").fetchone()
                if not first <= week <= last:
                    raise ValueError(f"no data for the week of {week}: weeks run from {first} to {last}")
            return breaches(con, week, patient_group)


def build(db_path: Path = DEFAULT_DB) -> MCPServer:
    tools = EdTools(db_path)

    def guarded(fn, *args) -> dict:
        try:
            return fn(*args)
        except ValueError as e:
            return {"error": str(e)}

    def list_weeks() -> dict:
        """The weeks with data (Monday starts), the last full week, the patient groups with their target hours,
        and the ten sites. Start here."""
        return guarded(tools.list_weeks)

    def site_breaches(week_start: str | None = None, patient_group: str = GROUP) -> dict:
        """Which sites breached the target in one week, worst first, with every site's 90th percentile hours,
        patient count, share within target and bed occupancy. week_start is any YYYY-MM-DD day in the week
        (default: the last full week). patient_group is admitted (default), high_urgency_sent_home or
        low_urgency_sent_home. Sites with fewer than 20 patients are listed in not_reported, not as passing."""
        return guarded(tools.site_breaches, week_start, patient_group)

    server = MCPServer(name="ed-wait-times", instructions=INSTRUCTIONS)
    for fn in (list_weeks, site_breaches):
        server.add_tool(fn, structured_output=False)
    return server


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m ed_wait_times.server")
    p.add_argument("--db", type=Path, default=Path(os.environ.get(DB_ENV, DEFAULT_DB)))
    args = p.parse_args()
    build(args.db).run("stdio")


if __name__ == "__main__":
    main()
