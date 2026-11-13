"""The governed metric service: the only way to get a number out of the HR warehouse.

    store = MetricStore.open(role="people_manager")
    store.query_metric("attrition_rate_12m", "2026-09", group_by=["department"])

Every answer comes from a definition in metrics.yml and says which one (`source`, `version`, `definition`).
The role is fixed when the store is opened. A metric or breakdown the role may not see is declined with a
reason, and pay metrics are withheld for any group smaller than `small_group_min` people. Nothing here takes
SQL from outside: column names come from metrics.yml and are checked against the model when the store opens,
and filter values are bound as parameters on a read-only connection.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

import duckdb
import yaml

from trusted_metrics_agent.load import DEFAULT_DB

HERE = Path(__file__).resolve().parent
CATALOG = HERE / "metrics.yml"
SOURCE = "trusted_metrics_agent/metrics.yml"
SENSITIVE = {"confidential", "restricted"}  # small groups withheld
ROUND = {"usd": 2, "share": 4, "months": 1, "people": 0}
MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class Declined(Exception):
    """The role may not see this. The message says why, without any of the withheld values."""


@dataclass(frozen=True)
class Metric:
    name: str
    label: str
    definition: str
    numerator: list[str]
    unit: str
    sensitivity: str
    owner: str
    version: int
    denominator: list[str] | None = None
    scale: float = 1.0
    people: str = "headcount"
    first_month: str | None = None

    def card(self) -> dict:
        return {"metric": self.name, "label": self.label, "definition": self.definition, "unit": self.unit,
                "sensitivity": self.sensitivity, "owner": self.owner, "version": self.version,
                "source": f"{SOURCE}#{self.name}"}


@dataclass(frozen=True)
class Catalog:
    model: str
    dimensions: list[str]
    first_month: str
    small_group_min: int
    metrics: dict[str, Metric]
    roles: dict[str, dict]

    @classmethod
    def load(cls, path: Path = CATALOG) -> Catalog:
        raw = yaml.safe_load(path.read_text())
        metrics = {name: Metric(name=name, **spec) for name, spec in raw["metrics"].items()}
        cat = cls(raw["model"], raw["dimensions"], raw["first_month"], raw["small_group_min"], metrics, raw["roles"])
        for role, spec in cat.roles.items():
            unknown = set(spec["metrics"]) - set(metrics) | set(spec["group_by"]) - set(cat.dimensions)
            if unknown:
                raise ValueError(f"role {role} names unknown metrics or dimensions: {sorted(unknown)}")
        return cat

    def columns(self) -> set[str]:
        cols = set(self.dimensions)
        for m in self.metrics.values():
            cols |= set(m.numerator) | set(m.denominator or []) | {m.people}
        return cols

    def roles_that_see(self, metric: str) -> list[str]:
        return [r for r, spec in self.roles.items() if metric in spec["metrics"]]


class MetricStore:
    def __init__(self, con: duckdb.DuckDBPyConnection, role: str, catalog: Catalog):
        if role not in catalog.roles:
            raise ValueError(f"unknown role {role!r}; roles: {sorted(catalog.roles)}")
        self.con, self.role, self.catalog = con, role, catalog
        self.policy = catalog.roles[role]
        have = {c for (c,) in con.execute(
            "select column_name from information_schema.columns where table_name = ?", [catalog.model]).fetchall()}
        missing = catalog.columns() - have
        if missing:
            raise ValueError(f"{catalog.model} is missing columns named in metrics.yml: {sorted(missing)}")

    @classmethod
    def open(cls, role: str, db_path: Path = DEFAULT_DB, catalog: Catalog | None = None) -> MetricStore:
        return cls(duckdb.connect(str(db_path), read_only=True), role, catalog or Catalog.load())

    @cached_property
    def last_month(self) -> str:
        (m,) = self.con.execute(f"select strftime(max(month_end), '%Y-%m') from {self.catalog.model}").fetchone()
        return m

    @cached_property
    def values(self) -> dict[str, list]:
        """The values each dimension takes, for filters and for telling a caller what exists."""
        return {d: [v for (v,) in self.con.execute(
            f"select distinct {d} from {self.catalog.model} order by 1").fetchall()] for d in self.catalog.dimensions}

    # ---- the three tools

    def list_metrics(self) -> dict:
        """The metrics this role can query, how it may break them down, and the months with data."""
        return {
            "role": self.role,
            "role_description": self.policy["description"],
            "metrics": [self.catalog.metrics[m].card() for m in self.policy["metrics"]],
            "group_by_allowed": self.policy["group_by"],
            "dimension_values": {d: self.values[d] for d in self.policy["group_by"]},
            "months": {"first": self.catalog.first_month, "last": self.last_month},
        }

    def describe_metric(self, metric: str) -> dict:
        """One metric's governed definition, and whether this role may query it."""
        m = self._metric(metric)
        card = m.card() | {"model": self.catalog.model, "numerator": m.numerator, "denominator": m.denominator,
                           "first_month": m.first_month or self.catalog.first_month}
        card["your_role_can_query"] = metric in self.policy["metrics"]
        if not card["your_role_can_query"]:
            card["roles_that_can"] = self.catalog.roles_that_see(metric)
        return card

    def query_metric(self, metric: str, start_month: str, end_month: str | None = None,
                     group_by: list[str] | None = None, filters: dict[str, str | int] | None = None) -> dict:
        """Values of one governed metric for a month or a range of months (YYYY-MM), optionally by group."""
        m = self._metric(metric)
        group_by, filters = list(group_by or []), dict(filters or {})
        if metric not in self.policy["metrics"]:
            raise Declined(f"role {self.role} cannot see {metric} ({m.sensitivity}); "
                           f"roles that can: {', '.join(self.catalog.roles_that_see(metric))}")
        for d in [*group_by, *filters]:
            if d not in self.catalog.dimensions:
                raise ValueError(f"unknown dimension {d!r}; dimensions: {self.catalog.dimensions}")
            if d not in self.policy["group_by"]:
                allowed = ", ".join(self.policy["group_by"]) or "none (company totals only)"
                raise Declined(f"role {self.role} cannot break {metric} down by {d}; allowed: {allowed}")
        for d, v in filters.items():
            if d == "job_level" and str(v).isdigit():
                filters[d] = v = int(v)
            if v not in self.values[d]:
                raise ValueError(f"no {d} {v!r}; values: {self.values[d]}")
        start, end = self._months(m, start_month, end_month or start_month)

        num = " + ".join(m.numerator)
        den = " + ".join(m.denominator) if m.denominator else "1"
        dims = "".join(f", {d}" for d in group_by)
        where = "".join(f" and {d} = ?" for d in filters)
        sql = (f"select strftime(month_end, '%Y-%m') as month{dims}, sum({num}) as n, sum({den}) as d, "
               f"sum({m.people}) as people from {self.catalog.model} "
               f"where month_end between last_day(?::date) and last_day(?::date){where} "
               f"group by all order by all")
        months: dict[str, list[tuple[dict, int]]] = {}
        for month, *rest in self.con.execute(sql, [f"{start}-01", f"{end}-01", *filters.values()]).fetchall():
            *keys, n, d, people = rest
            if group_by and people == 0 and n == 0:
                continue  # a group with nobody in it that month
            row = {"month": month, **dict(zip(group_by, keys, strict=True)), "value": _value(m, n, d)}
            months.setdefault(month, []).append((row, people))
        rows = []
        for groups in months.values():
            if m.sensitivity in SENSITIVE:
                self._withhold(groups)
            rows += [row for row, _ in groups]
        return m.card() | {"role": self.role, "model": self.catalog.model, "group_by": group_by, "filters": filters,
                           "rows": rows, "withheld_groups": sum("withheld" in r for r in rows)}

    def _withhold(self, groups: list[tuple[dict, int]]) -> None:
        """Blank pay values for groups under the minimum size. If that blanks exactly one group in a month, also
        blank the next smallest, so the hidden value cannot be recovered as the total minus the shown groups."""
        k = self.catalog.small_group_min
        small = [row for row, people in groups if people < k]
        for row in small:
            row |= {"value": None, "withheld": f"fewer than {k} people"}
        if len(small) == 1 and len(groups) > 1:
            row = min((g for g in groups if g[0] is not small[0]), key=lambda g: g[1])[0]
            row |= {"value": None, "withheld": "withheld so the smaller group cannot be worked out from the total"}

    # ---- helpers

    def _metric(self, name: str) -> Metric:
        if name not in self.catalog.metrics:
            raise ValueError(f"{name!r} is not a governed metric; this role's metrics: {self.policy['metrics']}")
        return self.catalog.metrics[name]

    def _months(self, m: Metric, start: str, end: str) -> tuple[str, str]:
        for x in (start, end):
            if not MONTH.match(str(x)):
                raise ValueError(f"months are YYYY-MM, got {x!r}")
        first = max(self.catalog.first_month, m.first_month or self.catalog.first_month)
        if start > end:
            raise ValueError(f"start_month {start} is after end_month {end}")
        if start < first or end > self.last_month:
            raise ValueError(f"{m.name} has data from {first} to {self.last_month}")
        return start, end


def _value(m: Metric, n, d) -> float | int | None:
    if m.denominator and not d:
        return None  # nobody to divide by
    value = float(n) / float(d) * m.scale if m.denominator else float(n) * m.scale
    return int(round(value)) if m.unit == "people" else round(value, ROUND[m.unit])
