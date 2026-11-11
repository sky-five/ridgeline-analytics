"""Compare every governed metric (MetricFlow) with its independent check (checks.py), month by month."""
from dataclasses import dataclass
from pathlib import Path

import duckdb
import pandas as pd

from metric_glossary.checks import CHECKS

REL_TOL = 1e-9
ABS_TOL = 1e-6


@dataclass
class Result:
    name: str
    months: int  # months compared
    mismatches: list[tuple[str, float | None, float | None]]  # (month, governed, check)
    latest_month: str | None
    latest_value: float | None

    @property
    def ok(self) -> bool:
        return self.months > 0 and not self.mismatches


def _close(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= max(ABS_TOL, REL_TOL * max(abs(a), abs(b)))


def _num(v) -> float | None:
    return None if v is None or pd.isna(v) else float(v)


def compare(name: str, governed: dict[str, float | None], check: dict[str, float | None],
            current_month: str | None = None) -> Result:
    """Months with a value on either side must agree; a month missing on one side counts as a mismatch
    unless the other side is empty (None) or zero there. The latest value shown is the last full month
    (before current_month) with a non-zero value: ratios and mature-signup counts are empty or zero for
    the months whose outcome is not known yet."""
    bad = []
    for month in sorted(set(governed) | set(check)):
        g, c = governed.get(month), check.get(month)
        if month not in governed and not c:
            continue
        if month not in check and not g:
            continue
        if not _close(g, c):
            bad.append((month, g, c))
    filled = {m: v for m, v in governed.items() if v and (current_month is None or m < current_month)}
    latest = max(filled) if filled else None
    return Result(name, len(set(governed) | set(check)), bad, latest, filled.get(latest) if latest else None)


def governed_by_month(names: list[str]) -> dict[str, dict[str, float | None]]:
    from semantic import query

    out = {}
    for name in names:  # one query per metric: ratio metrics would otherwise share a join of all sources
        df = query([name], ["metric_time__month"])
        pairs = zip(df["metric_time__month"], df[name], strict=True)
        out[name] = {str(pd.Timestamp(m).date()): _num(v) for m, v in pairs}
    return out


def check_by_month(con: duckdb.DuckDBPyConnection, name: str, as_of: str) -> dict[str, float | None]:
    rows = con.sql(CHECKS[name].sql.format(as_of=as_of)).fetchall()
    return {str(m): _num(v) for m, v in rows}


def reconcile(warehouse: Path) -> list[Result]:
    from semantic import list_metrics

    names = [m.name for m in list_metrics()]
    missing = sorted(set(names) - set(CHECKS))
    if missing:
        raise ValueError(f"governed metrics with no independent check: {', '.join(missing)}")
    governed = governed_by_month(names)
    with duckdb.connect(str(warehouse)) as con:  # same config as MetricFlow's in-process connection
        as_of = str(con.sql("select max(date_day) from fct_mrr_daily").fetchone()[0])
        current = as_of[:8] + "01"
        return [compare(n, governed[n], check_by_month(con, n, as_of), current) for n in names]


def glossary_table(results: list[Result]) -> pd.DataFrame:
    """One row per governed metric for the glossary page: definition, version, latest value, check status."""
    import yaml

    from semantic import DBT_DIR, list_metrics

    spec = yaml.safe_load((DBT_DIR / "models" / "semantic" / "_metrics.yml").read_text(encoding="utf-8"))
    version = {m["name"]: m.get("config", {}).get("meta", {}).get("version") for m in spec["metrics"]}
    kind = {m["name"]: m["type"] for m in spec["metrics"]}
    by_name = {r.name: r for r in results}
    rows = []
    for m in list_metrics():
        r = by_name[m.name]
        rows.append({
            "name": m.name, "label": m.label, "description": m.description, "metric_type": kind[m.name],
            "version": version[m.name],
            "dimensions": ", ".join(d for d in m.dimensions if not d.startswith("metric_time")),
            "latest_month": r.latest_month, "latest_value": r.latest_value,
            "months_compared": r.months, "mismatched_months": len(r.mismatches),
            "reconciled": r.ok, "check_source": CHECKS[m.name].source, "check_sql": CHECKS[m.name].sql.strip(),
        })
    return pd.DataFrame(rows)
