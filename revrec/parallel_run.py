"""Run the SQL models and the Python reference side by side and list every number that differs."""

from __future__ import annotations

from datetime import date

import duckdb

from revrec import reference
from revrec.billing import Billing

BRIDGE_COLUMNS = {
    "opening": "opening_arr_cents",
    "new": "new_cents",
    "reactivation": "reactivation_cents",
    "expansion": "expansion_cents",
    "contraction": "contraction_cents",
    "churn": "churn_cents",
    "closing": "closing_arr_cents",
}


def _diff(name: str, sql: dict, ref: dict) -> list[str]:
    return [
        f"{name} {key}: sql={sql.get(key)} reference={ref.get(key)}"
        for key in sorted(set(sql) | set(ref))
        if sql.get(key, 0) != ref.get(key, 0)
    ]


def compare(con: duckdb.DuckDBPyConnection, billing: Billing, as_of: date) -> tuple[int, list[str]]:
    """Returns (numbers compared, differences). An empty list means the two agree to the cent."""
    sql_rev = dict(con.execute("select month_start, recognized_cents from fct_revenue_monthly").fetchall())
    sql_def = dict(con.execute("select month_start, closing_cents from fct_deferred_revenue").fetchall())
    cols = ", ".join(BRIDGE_COLUMNS.values())
    sql_bridge = {
        r[0]: dict(zip(BRIDGE_COLUMNS, r[1:], strict=True))
        for r in con.execute(f"select month_start, {cols} from fct_arr_bridge").fetchall()
    }

    ref_rev = reference.revenue_by_month(billing)
    ref_def = reference.deferred_closing(billing, as_of)
    ref_bridge = reference.arr_bridge(billing, as_of)

    diffs = _diff("revenue", sql_rev, ref_rev) + _diff("deferred closing", sql_def, ref_def)
    compared = len(set(sql_rev) | set(ref_rev)) + len(set(sql_def) | set(ref_def))
    for m in sorted(set(sql_bridge) | set(ref_bridge)):
        diffs += _diff(f"ARR {m}", sql_bridge.get(m, {}), ref_bridge.get(m, {}))
        compared += len(BRIDGE_COLUMNS)
    return compared, diffs
