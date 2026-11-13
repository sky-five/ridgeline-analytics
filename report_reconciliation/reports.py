"""The three reports: their mart, grain, measures, inputs, lineage, and the expected numbers recomputed in
pandas straight from the source tables, without the SQL that built the mart."""
from collections.abc import Callable
from dataclasses import dataclass

import pandas as pd

BOOKKEEPING = {"source_extracted_at": "earliest extract among the report's input tables",
               "built_at": "when the mart was built"}


@dataclass(frozen=True)
class Report:
    name: str
    title: str
    mart: str
    grain: tuple[str, ...]
    measures: tuple[str, ...]
    inputs: tuple[str, ...]
    lineage: dict[str, str]  # mart column -> source columns it comes from, or how it is derived
    expected: Callable[[dict[str, pd.DataFrame]], pd.DataFrame]
    refresh_sla_hours: int = 24


def costed(src: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Approved timesheet entries priced at the rate in effect on the work date."""
    t = src["timesheets"]
    t = t[t["status"] == "approved"].copy()
    t["work_date"] = pd.to_datetime(t["work_date"])
    rates = src["rate_history"].copy()
    rates["valid_from"] = pd.to_datetime(rates["valid_from"])
    t = pd.merge_asof(t.sort_values("work_date"), rates.sort_values("valid_from"), left_on="work_date",
                      right_on="valid_from", by="resource_id", direction="backward")
    t["cost"] = (t["hours"] * t["hourly_cost"]).round(2)
    return t.merge(src["projects"][["project_id", "billable"]], on="project_id")


def project_hours(src):
    t = costed(src)
    t["month"] = t["work_date"].dt.to_period("M").dt.start_time.dt.date
    return t.groupby(["project_id", "month"], as_index=False)[["hours", "cost"]].sum()


def utilisation(src):
    t = costed(src)
    t["week_start"] = (t["work_date"] - pd.to_timedelta(t["work_date"].dt.weekday, unit="D")).dt.date
    t["billable_hours"] = t["hours"].where(t["billable"], 0.0)
    return t.groupby(["resource_id", "week_start"], as_index=False)[["hours", "billable_hours"]].sum()


def budget_burn(src):
    cost = costed(src).groupby("project_id")["cost"].sum().rename("cost_to_date")
    out = src["projects"][["project_id", "budget_cost"]].merge(cost, on="project_id", how="left")
    return out.fillna({"cost_to_date": 0.0})


TS, PR, RH, RS = "timesheets", "projects", "rate_history", "resources"
REPORTS = (
    Report("project_hours", "Project hours and cost by month", "mart.project_hours_monthly",
           ("project_id", "month"), ("hours", "cost"), (TS, PR, RH),
           {"project_id": f"{TS}.project_id", "month": f"{TS}.work_date",
            "hours": f"{TS}.hours", "cost": f"{TS}.hours, {RH}.hourly_cost"}, project_hours),
    Report("utilisation", "Resource utilisation by week", "mart.resource_utilisation_weekly",
           ("resource_id", "week_start"), ("hours", "billable_hours"), (TS, RS, PR, RH),
           {"resource_id": f"{TS}.resource_id", "week_start": f"{TS}.work_date", "hours": f"{TS}.hours",
            "billable_hours": f"{TS}.hours, {PR}.billable", "capacity_hours": f"{RS}.weekly_capacity_hours",
            "utilisation": f"{TS}.hours, {PR}.billable, {RS}.weekly_capacity_hours"}, utilisation),
    Report("budget_burn", "Project budget burn", "mart.project_budget_burn",
           ("project_id",), ("budget_cost", "cost_to_date"), (TS, PR, RH),
           {"project_id": f"{PR}.project_id", "status": f"{PR}.status", "budget_cost": f"{PR}.budget_cost",
            "cost_to_date": f"{TS}.hours, {RH}.hourly_cost",
            "burn_pct": f"{TS}.hours, {RH}.hourly_cost, {PR}.budget_cost"}, budget_burn),
)
