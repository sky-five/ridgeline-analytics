"""Source -> staging -> mart in DuckDB, the way the three reports are built.

`faults` plants one known mistake so the checks can be shown to catch it:
  rate_join_fan_out        join rates on resource_id only, ignoring the effective dates
  rejected_included        drop the approved-only filter
  closed_projects_dropped  inner join to active projects only
  stale_extract            the timesheet extract is 30 hours old
  undocumented_column      a mart column with no lineage entry
"""
import duckdb

FAULTS = ("rate_join_fan_out", "rejected_included", "closed_projects_dropped", "stale_extract",
          "undocumented_column")


def build(con: duckdb.DuckDBPyConnection, built_at, fault: str | None = None) -> None:
    if fault is not None and fault not in FAULTS:
        raise ValueError(f"unknown fault {fault!r}")
    rate_join = ("r.resource_id = t.resource_id" if fault == "rate_join_fan_out" else
                 "r.resource_id = t.resource_id and t.work_date >= r.valid_from "
                 "and (r.valid_to is null or t.work_date < r.valid_to)")
    status = "" if fault == "rejected_included" else "and t.status = 'approved'"
    projects = ("(select * from source.projects where status = 'active')" if fault == "closed_projects_dropped"
                else "source.projects")
    if fault == "stale_extract":
        con.execute("update source.extract_log set extracted_at = extracted_at - interval 30 hour "
                    "where table_name = 'timesheets'")
    con.execute("create schema if not exists staging; create schema if not exists mart")
    con.execute(f"""
        create or replace table staging.timesheet_costed as
        select t.entry_id, t.resource_id, t.project_id, t.work_date, t.hours, p.billable,
               r.hourly_cost, round(t.hours * r.hourly_cost, 2) as cost
        from source.timesheets t
        join {projects} p on p.project_id = t.project_id
        join source.rate_history r on {rate_join}
        where true {status}""")

    def extracted(*tables: str) -> str:
        names = ", ".join(f"'{t}'" for t in tables)
        return f"(select min(extracted_at) from source.extract_log where table_name in ({names}))"

    meta = f"timestamp '{built_at}' as built_at"
    con.execute(f"""
        create or replace table mart.project_hours_monthly as
        select project_id, date_trunc('month', work_date)::date as month,
               sum(hours) as hours, sum(cost) as cost,
               {extracted('timesheets', 'projects', 'rate_history')} as source_extracted_at, {meta}
        from staging.timesheet_costed group by 1, 2""")
    margin = ", 0.0 as margin_pct" if fault == "undocumented_column" else ""
    con.execute(f"""
        create or replace table mart.resource_utilisation_weekly as
        select s.resource_id, date_trunc('week', s.work_date)::date as week_start,
               sum(s.hours) as hours, sum(s.hours) filter (where s.billable) as billable_hours,
               any_value(r.weekly_capacity_hours) as capacity_hours,
               round(coalesce(sum(s.hours) filter (where s.billable), 0) / any_value(r.weekly_capacity_hours), 4)
                 as utilisation{margin},
               {extracted('timesheets', 'resources', 'projects', 'rate_history')} as source_extracted_at, {meta}
        from staging.timesheet_costed s join source.resources r using (resource_id) group by 1, 2""")
    con.execute(f"""
        create or replace table mart.project_budget_burn as
        select p.project_id, p.status, p.budget_cost, coalesce(sum(s.cost), 0) as cost_to_date,
               round(coalesce(sum(s.cost), 0) / p.budget_cost, 4) as burn_pct,
               {extracted('timesheets', 'projects', 'rate_history')} as source_extracted_at, {meta}
        from {projects} p left join staging.timesheet_costed s using (project_id) group by 1, 2, 3""")
