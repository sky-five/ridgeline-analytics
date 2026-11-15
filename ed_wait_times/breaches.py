"""Which sites breached the 8-hour target for admitted patients in a week: the 90th percentile of their hours in
the ED, over that week's admitted patients, is above 8. A site with fewer than 20 admitted patients that week is
listed as not reported rather than as passing. Read-only: it only selects from the site_week mart."""
from datetime import date, timedelta

import duckdb

GROUP = "admitted"


def last_full_week(con: duckdb.DuckDBPyConnection) -> date:
    """The Monday of the latest week that has all seven days in the bed census."""
    last = con.sql("select max(census_date) from stg_ed__bed_census").fetchone()[0]
    sunday = last - timedelta(days=(last.weekday() + 1) % 7)
    return sunday - timedelta(days=6)


def breaches(con: duckdb.DuckDBPyConnection, week_start: date | None = None, group: str = GROUP) -> dict:
    """Every site's figure for one week, worst first, and the list of sites over target."""
    week_start = week_start or last_full_week(con)
    rows = con.execute(
        """
        select s.site_id, d.site_type, d.region, s.patients, s.p90_los_hours, s.share_within_target,
               s.target_hours, s.reportable, s.breached, s.mean_bed_occupancy
        from site_week as s
        inner join dim_sites as d using (site_id)
        where s.week_start = ? and s.patient_group = ?
        order by s.reportable desc, s.p90_los_hours desc
        """,
        [week_start, group],
    ).df()
    sites = [
        {"site_id": r.site_id, "site_type": r.site_type, "region": r.region, "patients": int(r.patients),
         "p90_hours": round(float(r.p90_los_hours), 2), "share_within_target": round(float(r.share_within_target), 4),
         "mean_bed_occupancy": round(float(r.mean_bed_occupancy), 4), "reported": bool(r.reportable),
         "breached": bool(r.breached)}
        for r in rows.itertuples()
    ]
    return {
        "week_start": week_start.isoformat(),
        "week_end": (week_start + timedelta(days=6)).isoformat(),
        "patient_group": group,
        "target_hours": int(rows["target_hours"].iloc[0]) if len(rows) else None,
        "breached": [s["site_id"] for s in sites if s["breached"]],
        "not_reported": [s["site_id"] for s in sites if not s["reported"]],
        "sites": sites,
    }
