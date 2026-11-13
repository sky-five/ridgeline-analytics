"""Seeded synthetic project, resource and time data: the source tables the reports are built from.

  source.projects        18 projects, 2 internal (non-billable), 3 closed before the end of the half
  source.resources       30 people with a role and weekly capacity; some join mid-half
  source.rate_history    effective-dated cost rates; about a third of people get a raise during the half
  source.timesheets      one or two entries per person per working day; approved, rejected or still submitted
  source.extract_log     when each source table was last extracted
"""
from datetime import date, datetime, timedelta

import duckdb
import numpy as np
import pandas as pd

START, END = date(2026, 1, 5), date(2026, 6, 26)  # Mondays to Fridays, 25 weeks
AS_OF = datetime(2026, 6, 29, 7, 0)  # when the checks run: Monday morning after the last week
EXTRACTED_AT = datetime(2026, 6, 29, 5, 30)
BUILT_AT = datetime(2026, 6, 29, 6, 0)
ROLES = {"analyst": 85.0, "engineer": 110.0, "lead": 140.0, "designer": 95.0}
SOURCE_TABLES = ("projects", "resources", "rate_history", "timesheets")


def frames(seed: int = 11) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    n_proj = 18
    projects = pd.DataFrame({
        "project_id": [f"P{i:02d}" for i in range(1, n_proj + 1)],
        "project_name": [f"Project {i:02d}" for i in range(1, n_proj + 1)],
        "billable": [i not in (4, 11) for i in range(1, n_proj + 1)],
        "start_date": [START + timedelta(weeks=int(w)) for w in rng.integers(0, 8, n_proj)],
    })
    projects["end_date"] = None
    closed = [2, 7, 13]
    projects.loc[closed, "end_date"] = [date(2026, 3, 27), date(2026, 4, 24), date(2026, 5, 29)]
    projects["status"] = np.where(projects["end_date"].isna(), "active", "closed")
    projects["budget_cost"] = (rng.integers(60, 260, n_proj) * 1000).astype(float)

    n_res = 30
    roles = rng.choice(list(ROLES), n_res, p=[0.35, 0.35, 0.15, 0.15])
    resources = pd.DataFrame({
        "resource_id": [f"R{i:02d}" for i in range(1, n_res + 1)],
        "role": roles,
        "weekly_capacity_hours": np.where(rng.random(n_res) < 0.15, 32.0, 40.0),
        "start_date": [START if rng.random() < 0.8 else START + timedelta(weeks=int(rng.integers(4, 16)))
                       for _ in range(n_res)],
    })

    rates = []
    for r in resources.itertuples():
        base = ROLES[r.role] + float(rng.integers(-10, 11))
        if rng.random() < 0.35:
            raise_on = max(START + timedelta(weeks=int(rng.integers(6, 22))), r.start_date + timedelta(weeks=4))
            rates += [(r.resource_id, r.start_date, raise_on, base), (r.resource_id, raise_on, None, base * 1.08)]
        else:
            rates.append((r.resource_id, r.start_date, None, base))
    rate_history = pd.DataFrame(rates, columns=["resource_id", "valid_from", "valid_to", "hourly_cost"])
    rate_history["hourly_cost"] = rate_history["hourly_cost"].round(2)

    rows = []
    days = [START + timedelta(days=d) for d in range((END - START).days + 1)]
    days = [d for d in days if d.weekday() < 5]
    for r in resources.itertuples():
        assigned = rng.choice(n_proj, 3, replace=False)
        for d in days:
            if d < r.start_date or rng.random() < 0.06:  # not started yet, or a day off
                continue
            open_ = [i for i in assigned if projects.start_date[i] <= d
                     and (projects.end_date[i] is None or d <= projects.end_date[i])]
            if not open_:
                open_ = [3]  # internal project 04 takes the time
            hours_day = r.weekly_capacity_hours / 5 * float(rng.choice([0.75, 0.875, 1.0, 1.0, 1.0625]))
            picks = rng.choice(open_, min(len(open_), int(rng.integers(1, 3))), replace=False)
            split = [hours_day] if len(picks) == 1 else [round(hours_day * 0.5 * 4) / 4] * 2
            for i, h in zip(picks, split, strict=True):
                status = rng.choice(["approved", "rejected", "submitted"], p=[0.955, 0.02, 0.025])
                rows.append((r.resource_id, projects.project_id[i], d, round(h * 4) / 4, status))
    timesheets = pd.DataFrame(rows, columns=["resource_id", "project_id", "work_date", "hours", "status"])
    timesheets.insert(0, "entry_id", [f"T{i:06d}" for i in range(1, len(timesheets) + 1)])

    extract_log = pd.DataFrame({"table_name": list(SOURCE_TABLES), "extracted_at": [EXTRACTED_AT] * 4})
    return {"projects": projects, "resources": resources, "rate_history": rate_history,
            "timesheets": timesheets, "extract_log": extract_log}


def load(con: duckdb.DuckDBPyConnection, data: dict[str, pd.DataFrame]) -> None:
    con.execute("create schema if not exists source")
    for name, df in data.items():
        con.register("_df", df)
        con.execute(f"create or replace table source.{name} as select * from _df")
        con.unregister("_df")
    for col in ("start_date", "end_date"):
        con.execute(f"alter table source.projects alter {col} type date")
    for col in ("valid_from", "valid_to"):
        con.execute(f"alter table source.rate_history alter {col} type date")
    con.execute("alter table source.resources alter start_date type date")
    con.execute("alter table source.timesheets alter work_date type date")
