"""The three read-only tools an AI analyst gets over the metric registry's semantic layer.

    list_metrics    every metric with its version, owner and group-bys, the filter values and the dates
    explain_metric  one metric from registry.yml: definition, formula, changelog, fingerprint, glossary terms
    query_metrics   values from MetricFlow, with the SQL MetricFlow ran for exactly that query

There is no SQL tool. A query names registry metrics, group-bys and filters; every name and value is checked
against the registry and the data before MetricFlow builds the SQL, so a caller cannot reach a table or a
definition the registry does not hold, and nothing it asks can write. Errors come back as {"error": ...}.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pandas as pd

from metric_registry import compile as registry
from metric_registry import metrics as layer
from metric_registry.load import DEFAULT_DB
from metric_registry.simulate import AS_OF, FIRST_DAY

SOURCE = "metric_registry/registry.yml#{}"
GRAINS = ("month", "quarter", "year")
TIME = {f"metric_time__{g}" for g in GRAINS}
MAX_ROWS = 200
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _cell(name: str, value):
    if name == "metric_time__quarter":
        ts = pd.Timestamp(value)
        return f"{ts.year}-Q{ts.quarter}"
    if name == "metric_time__month":
        return pd.Timestamp(value).strftime("%Y-%m")
    if name == "metric_time__year":
        return pd.Timestamp(value).year
    if isinstance(value, bool | str) or value is None:
        return value
    v = round(float(value), 4)
    return int(v) if v.is_integer() else v


class SemanticTools:
    """Plain methods returning JSON-ready dicts; the MCP server and the tests both use them."""

    def __init__(self, db: Path = DEFAULT_DB):
        self.db = Path(db)
        self.reg = registry.load_registry()
        self._values: dict[str, list] | None = None

    # ---- helpers

    def _dims(self, metric: str) -> list[str]:
        return [d for d in registry.dimensions(self.reg, metric) if d != "metric_time"]

    def values(self) -> dict[str, list]:
        """Every categorical dimension's values, read once through MetricFlow (units sold by each)."""
        if self._values is None:
            dims = sorted({d for m in self.reg["metrics"] for d in self._dims(m)})
            out = {}
            for d in dims:
                metric = next(m for m in self.reg["metrics"] if d in self._dims(m))
                df = layer.query([metric], [d], db=self.db)
                out[d] = sorted(v.item() if hasattr(v, "item") else v for v in df[d.lower()].tolist())
            self._values = out
        return self._values

    @staticmethod
    def _literal(value) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        return "'" + str(value).replace("'", "''") + "'"

    # ---- the tools

    def list_metrics(self) -> dict:
        """Every governed metric (name, label, definition, version, owner, the group-bys it allows), the
        values each filter dimension takes, and the first and last day with data. Start here."""
        out = []
        for name, m in self.reg["metrics"].items():
            out.append({"metric": name, "label": m["label"], "definition": m["definition"],
                        "kind": "simple" if "measure" in m else "ratio", "version": m["version"],
                        "owner": m["owner"], "group_by": [*sorted(TIME), *self._dims(name)]})
        return {"metrics": out, "dimension_values": self.values(),
                "dates": {"first": FIRST_DAY.isoformat(), "last": AS_OF.isoformat()}}

    def explain_metric(self, metric: str) -> dict:
        """The registry entry behind one metric: definition, how it is computed, version, owner, changelog,
        fingerprint, the group-bys it allows and the glossary terms its definition uses."""
        m = self.reg["metrics"].get(metric)
        if m is None:
            return {"error": f"unknown metric {metric!r}; one of {', '.join(self.reg['metrics'])}"}
        text = m["definition"].lower()
        terms = {t: d for t, d in self.reg["glossary"].items() if t.lower() in text or t.lower() in m["label"].lower()}
        return {"metric": metric, "source": SOURCE.format(metric), "label": m["label"],
                "definition": m["definition"], "computed_as": registry.formula(self.reg, metric),
                "version": m["version"], "owner": m["owner"],
                "changelog": {str(k): v for k, v in sorted(m["changelog"].items())},
                "fingerprint": registry.fingerprint(self.reg, metric),
                "group_by": [*sorted(TIME), *self._dims(metric)], "glossary": terms}

    def where(self, metric_names: list[str], filters: dict | None, start_date: str | None,
              end_date: str | None) -> list[str] | dict:
        """MetricFlow where-clauses from checked filters and dates, or an {"error"}."""
        allowed = set.intersection(*(set(self._dims(m)) for m in metric_names))
        out = []
        for dim, value in (filters or {}).items():
            if dim not in allowed:
                return {"error": f"cannot filter {', '.join(metric_names)} by {dim!r}; filters: "
                                 f"{', '.join(sorted(allowed))}"}
            known = self.values()[dim]
            if isinstance(known[0], bool) and isinstance(value, str) and value.lower() in ("true", "false"):
                value = value.lower() == "true"
            if value not in known:
                return {"error": f"{dim} has no value {value!r}; values: {', '.join(map(str, known))}"}
            out.append(f"{{{{ Dimension('{dim}') }}}} = {self._literal(value)}")
        for op, day in ((">=", start_date), ("<=", end_date)):
            if day is None:
                continue
            if not DAY.match(str(day)):
                return {"error": f"dates are YYYY-MM-DD, got {day!r}"}
            try:
                date.fromisoformat(day)
            except ValueError:
                return {"error": f"no such day {day!r}"}
            out.append(f"{{{{ TimeDimension('metric_time', 'day') }}}} {op} '{day}'")
        return out

    def query_metrics(self, metrics: list[str], group_by: list[str] | None = None,
                      filters: dict[str, str] | None = None, start_date: str | None = None,
                      end_date: str | None = None) -> dict:
        """Values of one or more governed metrics from MetricFlow, and the SQL it ran for them.

        Args:
            metrics: Metric names from list_metrics.
            group_by: Optional group-bys: metric_time__month, metric_time__quarter, metric_time__year, or a
                dimension such as vehicle__segment.
            filters: Optional {dimension: value}, e.g. {"vehicle__segment": "ev"}; values from list_metrics.
            start_date: First sale day to include, YYYY-MM-DD.
            end_date: Last sale day to include, YYYY-MM-DD.
        """
        names = list(dict.fromkeys(metrics or []))
        if not names:
            return {"error": "name at least one metric"}
        unknown = [m for m in names if m not in self.reg["metrics"]]
        if unknown:
            return {"error": f"unknown metric {unknown[0]!r}; one of {', '.join(self.reg['metrics'])}"}
        group_by = list(dict.fromkeys(group_by or []))
        shared = sorted(set.intersection(*(set(self._dims(m)) for m in names)))
        for g in group_by:
            if g not in TIME and g not in shared:
                return {"error": f"cannot group {', '.join(names)} by {g!r}; group-bys: "
                                 f"{', '.join([*sorted(TIME), *shared])}"}
        where = self.where(names, filters, start_date, end_date)
        if isinstance(where, dict):
            return where
        result = layer.run(names, group_by, where, db=self.db)
        df = result["df"]
        if len(df) > MAX_ROWS:
            return {"error": f"{len(df)} rows; group by less or filter (at most {MAX_ROWS})"}
        rows = [{c: _cell(c, r[c]) for c in df.columns} for r in df.to_dict("records")]
        return {"metrics": {m: {"version": self.reg["metrics"][m]["version"], "source": SOURCE.format(m)}
                            for m in names},
                "group_by": group_by, "filters": filters or {}, "start_date": start_date, "end_date": end_date,
                "rows": rows, "sql": result["sql"]}

    def all(self) -> list:
        return [self.list_metrics, self.explain_metric, self.query_metrics]
