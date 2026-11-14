"""Read the marts, review the claims, size the return, and write results/summary.json and
results/utilisation_weekly.csv."""
import json
from pathlib import Path

import duckdb
import pandas as pd

from or_utilisation import roi, validate
from or_utilisation.simulate import POLICY_START, Suite

RESULTS = Path(__file__).resolve().parent / "results"
SUMMARY = RESULTS / "summary.json"
WEEKLY = RESULTS / "utilisation_weekly.csv"
WEEKLY_COLUMNS = ["block_week", "period", "allocated_minutes", "credited_released_minutes", "owner_in_block_minutes",
                  "reused_in_block_minutes", "completed_cases", "cancelled_cases", "block_utilisation",
                  "adjusted_block_utilisation", "block_utilisation_with_turnover", "room_utilisation",
                  "released_time_rate", "same_day_cancellation_rate"]
RATES = ["block_utilisation", "adjusted_block_utilisation", "block_utilisation_with_turnover", "room_utilisation",
         "released_time_rate", "released_time_reuse_rate", "same_day_cancellation_rate"]


def marts(db: Path) -> dict[str, pd.DataFrame]:
    with duckdb.connect(str(db), read_only=True) as con:
        return {
            "by_period": con.execute("select * from main.utilisation_by_period").df(),
            "weekly": con.execute("select * from main.utilisation_weekly order by block_week").df(),
            "daily": con.execute("""
                select block_date, period, sum(allocated_minutes) as allocated_minutes,
                    sum(reused_in_block_minutes) as reused_in_block_minutes
                from main.fct_blocks group by block_date, period order by block_date""").df(),
        }


def summary(db: Path, suite: Suite) -> dict:
    m = marts(db)
    by_period, daily = m["by_period"], m["daily"]
    days = {p: daily.loc[daily["period"] == p, "block_date"].tolist() for p in ("before", "after")}
    periods = {
        f"{r.period}_{r.blocks_in_scope}": {k: round(float(getattr(r, k)), 4) for k in RATES if pd.notna(getattr(r, k))}
        | {"blocks": int(r.blocks), "completed_cases": int(r.completed_cases)}
        for r in by_period.itertuples()
    }
    return {
        "policy_start": POLICY_START.isoformat(),
        "rooms": int(suite.blocks["room_id"].nunique()),
        "block_days": int(daily["block_date"].nunique()),
        "blocks": len(suite.blocks),
        "releases": len(suite.releases),
        "auto_releases": int((suite.releases["release_type"] == "auto").sum()),
        "cases_booked": len(suite.cases),
        "cases_completed": int((suite.cases["status"] == "completed").sum()),
        "periods": dict(sorted(periods.items())),
        "claims": [validate.to_dict(validate.review(name, by_period, days)) for name in validate.CLAIMED],
        "roi": roi.to_dict(roi.roi(by_period, daily, suite.truth)),
        "assumptions": {"margin_per_patient_hour_usd": roi.MARGIN_PER_HOUR_USD, "rule_cost_usd": roi.RULE_COST_USD},
        "truth": suite.truth,
    }


def to_json(s: dict) -> str:
    return json.dumps(s, indent=2, default=str) + "\n"


def weekly_csv(db: Path) -> str:
    w = marts(db)["weekly"][WEEKLY_COLUMNS].copy()
    w["block_week"] = pd.to_datetime(w["block_week"]).dt.date
    for c in WEEKLY_COLUMNS[2:8]:
        w[c] = w[c].astype(int)
    return w.round(4).to_csv(index=False)
