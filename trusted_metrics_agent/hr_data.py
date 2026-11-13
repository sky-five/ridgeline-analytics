"""Synthetic HR and payroll exports for a roofing software company of about 300 people.

Three tables, as an HR system and a payroll system would export them:

- raw_hr.employees         one row per person ever employed: department, location, level, type, hire date
- raw_hr.salary_changes    annual base salary from a date on (the hire salary, then a raise each January)
- raw_hr.terminations      leaving date and reason (voluntary or involuntary)
- raw_payroll.pay_lines    what was paid each month: base (pro-rated for part months), overtime, March bonus

People keep their department, location and level for their whole stay, so a group's numbers move only
with hires and leavers. Everything comes from a fixed seed: the same call always gives the same rows.
There are no names, birth dates or other personal fields; employees are ids only.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache

import numpy as np
import pandas as pd

SEED = 1707
START = date(2024, 1, 1)  # first month the warehouse reports on
AS_OF = date(2026, 9, 30)  # last day of data; the README, tests and eval are pinned to it

# department: (people on 2024-01-01, hires per month, monthly leave probability, base salary at level 1)
DEPARTMENTS = {
    "Field Operations": (70, 2.6, 0.022, 52_000),
    "Customer Support": (40, 1.3, 0.016, 48_000),
    "Sales": (45, 1.6, 0.019, 58_000),
    "Engineering": (55, 1.4, 0.009, 92_000),
    "Finance": (12, 0.25, 0.007, 70_000),
    "People": (8, 0.2, 0.008, 64_000),
}
LOCATIONS = ["Ontario", "Alberta", "British Columbia", "Remote"]
LOCATION_P = {  # Field Operations works on site, so never remote
    "Field Operations": [0.45, 0.35, 0.20, 0.0],
    "default": [0.40, 0.15, 0.15, 0.30],
}
LEVEL_P = [0.40, 0.30, 0.18, 0.09, 0.03]  # levels 1-5
LEVEL_STEP = 1.22  # each level pays 22% more
PART_TIME = {"Field Operations": 0.12, "Customer Support": 0.20}
OVERTIME = {"Field Operations": 0.12, "Customer Support": 0.04}  # mean overtime as a share of base pay
P_VOLUNTARY = 0.7
RAISE = 0.03
BONUS_P = 0.06  # mean March bonus, share of annual base


@dataclass(frozen=True)
class Exports:
    employees: pd.DataFrame
    salary_changes: pd.DataFrame
    terminations: pd.DataFrame
    pay_lines: pd.DataFrame

    def tables(self) -> dict[str, pd.DataFrame]:
        return {
            "raw_hr.employees": self.employees,
            "raw_hr.salary_changes": self.salary_changes,
            "raw_hr.terminations": self.terminations,
            "raw_payroll.pay_lines": self.pay_lines,
        }


def month_ends(start: date, end: date) -> list[date]:
    out, y, m = [], start.year, start.month
    while date(y, m, 1) <= end:
        out.append(date(y, m, calendar.monthrange(y, m)[1]))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _cents(dollars: float) -> int:
    return int(round(dollars * 100))


@lru_cache(maxsize=1)
def exports() -> Exports:
    rng = np.random.default_rng(SEED)
    people = []  # dicts: emp_id, department, location, job_level, employment_type, hire_date, base, fte
    leaves = {}  # emp_id -> (term_date, reason)

    def hire(dept: str, when: date) -> None:
        emp_id = f"emp_{len(people) + 1:04d}"
        loc_p = LOCATION_P.get(dept, LOCATION_P["default"])
        level = int(rng.choice(5, p=LEVEL_P)) + 1
        part = rng.random() < PART_TIME.get(dept, 0.0)
        base = DEPARTMENTS[dept][3] * LEVEL_STEP ** (level - 1) * rng.uniform(0.92, 1.08)
        people.append({
            "emp_id": emp_id, "department": dept, "location": LOCATIONS[int(rng.choice(4, p=loc_p))],
            "job_level": level, "employment_type": "part_time" if part else "full_time", "hire_date": when,
            "base": round(base * (0.6 if part else 1.0), -2),
        })

    for dept, (n0, *_) in DEPARTMENTS.items():  # the people already there on day one
        for _ in range(n0):
            hire(dept, START - timedelta(days=int(rng.integers(30, 9 * 365))))

    for me in month_ends(START, AS_OF):
        first = me.replace(day=1)
        active = [p for p in people if p["hire_date"] <= me and p["emp_id"] not in leaves]
        for p in active:  # leavers this month (hired before the month started)
            if p["hire_date"] < first and rng.random() < DEPARTMENTS[p["department"]][2]:
                day = first + timedelta(days=int(rng.integers(0, me.day)))
                leaves[p["emp_id"]] = (day, "voluntary" if rng.random() < P_VOLUNTARY else "involuntary")
        for dept, (_, rate, _, _) in DEPARTMENTS.items():
            for _ in range(rng.poisson(rate)):
                hire(dept, first + timedelta(days=int(rng.integers(0, me.day))))

    employees = pd.DataFrame(
        [{k: p[k] for k in ("emp_id", "department", "location", "job_level", "employment_type", "hire_date")}
         for p in people]
    )
    terminations = pd.DataFrame(
        [{"emp_id": e, "term_date": d, "term_reason": r} for e, (d, r) in sorted(leaves.items())],
        columns=["emp_id", "term_date", "term_reason"],
    )

    salary_rows, pay_rows = [], []
    for p in people:
        end = leaves.get(p["emp_id"], (None,))[0]
        base = p["base"]
        salary_rows.append({"emp_id": p["emp_id"], "effective_date": p["hire_date"],
                            "annual_base_cents": _cents(base)})
        for year in range(max(p["hire_date"].year + 1, START.year), AS_OF.year + 1):
            jan1 = date(year, 1, 1)
            if end is not None and end <= jan1:
                break
            if year == START.year and p["hire_date"] >= jan1:
                continue
            base = round(base * (1 + RAISE), -2)
            salary_rows.append({"emp_id": p["emp_id"], "effective_date": jan1, "annual_base_cents": _cents(base)})
        # pay, month by month: base for the days employed, overtime for crews and support, March bonus
        by_date = sorted((r["effective_date"], r["annual_base_cents"]) for r in salary_rows
                         if r["emp_id"] == p["emp_id"])
        for me in month_ends(START, AS_OF):
            first = me.replace(day=1)
            lo, hi = max(first, p["hire_date"]), min(me, end - timedelta(days=1)) if end else me
            if hi < lo:
                continue
            annual = [c for d, c in by_date if d <= me][-1]
            days_paid = (hi - lo).days + 1
            base_pay = round(annual / 12 * days_paid / me.day)
            pay_rows.append((p["emp_id"], me, "base", base_pay))
            ot = OVERTIME.get(p["department"])
            if ot:
                pay_rows.append((p["emp_id"], me, "overtime", round(base_pay * rng.gamma(4.0, ot / 4.0))))
            if me.month == 3 and p["hire_date"] <= date(me.year - 1, 12, 31):
                pay_rows.append((p["emp_id"], me, "bonus", round(annual * rng.uniform(0, 2 * BONUS_P), -2)))

    salary_changes = pd.DataFrame(salary_rows).sort_values(["emp_id", "effective_date"], ignore_index=True)
    pay_lines = pd.DataFrame(pay_rows, columns=["emp_id", "pay_date", "pay_type", "amount_cents"])
    for df, cols in ((employees, ["hire_date"]), (terminations, ["term_date"]),
                     (salary_changes, ["effective_date"]), (pay_lines, ["pay_date"])):
        for c in cols:
            df[c] = pd.to_datetime(df[c]).dt.date
    return Exports(employees, salary_changes, terminations, pay_lines)
