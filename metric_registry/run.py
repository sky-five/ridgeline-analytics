"""Ask the semantic layer the first questions an incentives team asks, and write the answers to
results/summary.json. Every number comes from a MetricFlow query over the registry's metrics."""
import json
from pathlib import Path

import pandas as pd

from metric_registry import metrics
from metric_registry.simulate import AS_OF, Network

RESULTS = Path(__file__).resolve().parent / "results"
SUMMARY = RESULTS / "summary.json"
TOTALS = ["units_sold", "revenue", "incentive_spend", "customer_cash", "program_spend"]


def _key(name: str, value):
    if name == "metric_time__quarter":
        ts = pd.Timestamp(value)
        return f"{ts.year}-Q{ts.quarter}"
    return value


def _value(v) -> float | int:
    v = round(float(v), 4)
    return int(v) if v.is_integer() else v


def _rows(df: pd.DataFrame, keys: list[str]) -> list[dict]:
    out = []
    for r in df.to_dict("records"):
        row = {k.split("__")[-1]: _key(k, r[k]) for k in keys}
        out.append(row | {m: _value(r[m]) for m in df.columns if m not in keys})
    return out


def summary(db: Path, net: Network) -> dict:
    q = lambda ms, gb=None: metrics.query(ms, gb, db=db)  # noqa: E731
    catalogue = metrics.list_metrics(db)
    return {
        "as_of": AS_OF.isoformat(),
        "rows": {"dealers": len(net.dealers), "vehicles": len(net.vehicles), "programs": len(net.programs),
                 "sales": len(net.sales), "incentive_applications": len(net.incentives)},
        "metrics": {m["name"]: m["version"] for m in catalogue},
        "totals": _rows(q(TOTALS), [])[0],
        "headline": _rows(q(metrics.HEADLINE), [])[0],
        "by": {s.split("__")[-1]: _rows(q(metrics.HEADLINE, [s]), [s]) for s in metrics.SLICES},
        "quarter_end": _rows(q(["units_sold", "incentive_per_unit"], ["sale__is_quarter_end"]),
                             ["sale__is_quarter_end"]),
        "program_spend": _rows(q(["program_spend"], ["program__program_type"]), ["program__program_type"]),
        "quarterly": _rows(q(metrics.HEADLINE, ["metric_time__quarter"]), ["metric_time__quarter"]),
    }


def to_json(s: dict) -> str:
    return json.dumps(s, indent=2, default=str) + "\n"
