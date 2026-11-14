"""Ask the semantic layer the questions a claims team asks first, and write the answers to
results/summary.json. Every number comes from a MetricFlow query, not from hand-written SQL."""
import json
from pathlib import Path

import pandas as pd

from claims_self_service import metrics
from claims_self_service.simulate import AS_OF, HAIL_REGION, HAIL_START, Book

RESULTS = Path(__file__).resolve().parent / "results"
SUMMARY = RESULTS / "summary.json"


def _rows(df, keys: list[str]) -> list[dict]:
    out = []
    for r in df.to_dict("records"):
        if any(pd.isna(r[k]) for k in keys):
            continue  # closed-date measures put open claims (no closed date) in a null month
        row = {k.split("__")[-1]: (str(r[k])[:7] if k.startswith("metric_time") else r[k]) for k in keys}
        out.append(row | {m: round(float(r[m]), 4) for m in df.columns if m not in keys and pd.notna(r[m])})
    return out


def summary(db: Path, book: Book) -> dict:
    q = lambda ms, gb=None, where=None: metrics.query(ms, gb, where, db=db)  # noqa: E731
    hail_month = HAIL_START.strftime("%Y-%m")
    home_south = q(["loss_ratio", "claims_reported"], ["metric_time__month"],
                   ["{{ Dimension('policy__line_of_business') }} = 'homeowners'",
                    f"{{{{ Dimension('policy__region') }}}} = '{HAIL_REGION}'"])
    home_south = _rows(home_south, ["metric_time__month"])
    return {
        "as_of": AS_OF.isoformat(),
        "policies": len(book.policies),
        "claims": len(book.claims),
        "claims_by_status": {k: int(v) for k, v in book.claims["status"].value_counts().sort_index().items()},
        "metrics": [m["name"] for m in metrics.list_metrics(db)],
        "headline": _rows(q(metrics.HEADLINE + ["earned_premium", "incurred_losses"]), [])[0],
        "by": {s.split("__")[-1]: _rows(q(metrics.HEADLINE, [s]), [s]) for s in metrics.SLICES},
        "monthly": _rows(q(metrics.HEADLINE, ["metric_time__month"]), ["metric_time__month"]),
        "hail": {"region": HAIL_REGION, "month": hail_month,
                 "homeowners_by_month": home_south},
    }


def to_json(s: dict) -> str:
    return json.dumps(s, indent=2, default=str) + "\n"
