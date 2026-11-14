"""The claims self-service dashboard tables, from the committed semantic-layer answers (no warehouse needed).

`python -m claims_self_service` writes results/summary.json and results/metrics_monthly.csv from MetricFlow;
scripts/export_reporting.py turns them into reporting.claims_ss_* tables for the Evidence page.
The book is a separate simulated project, so its numbers are fixed and do not move with the nightly build.
"""
import json
from pathlib import Path

import pandas as pd
import yaml

HERE = Path(__file__).resolve().parent
SUMMARY = HERE / "results" / "summary.json"
CUBE = HERE / "results" / "metrics_monthly.csv"
METRICS_YML = HERE / "dbt" / "models" / "semantic" / "_metrics.yml"

LABELS = {
    "personal_auto": "Personal auto", "homeowners": "Homeowners", "commercial_property": "Commercial property",
    "east": "East", "north": "North", "south": "South", "west": "West",
    "agent": "Agent", "broker": "Broker", "direct": "Direct",
}
SLICE_LABELS = {"line_of_business": "Line of business", "region": "Region", "channel": "Channel"}

# What each headline metric should not be used for; the handover doc says the same in more words.
NOT_FIT_FOR = {
    "loss_ratio": "Recent months (claims not yet reported read as no loss) and any cut by peril "
                  "(premium is not earned by peril, so MetricFlow refuses it).",
    "claim_cycle_time_days": "Claims still open: it only counts closed claims, so a backlog of slow claims "
                             "makes it look better, not worse.",
    "approval_rate": "Withdrawn claims (left out) and claims still open; a month with few decisions swings widely.",
}


def _label(v: str) -> str:
    return LABELS.get(v, v)


def ratios(df: pd.DataFrame) -> pd.DataFrame:
    """The three headline ratios from summed additive metrics, as MetricFlow defines them in _metrics.yml."""
    return pd.DataFrame({
        "loss_ratio": df["incurred_losses"] / df["earned_premium"],
        "claim_cycle_time_days": df["cycle_days"] / df["closed_claims"].where(df["closed_claims"] > 0),
        "approval_rate": df["approved_claims"] / df["decided_claims"].where(df["decided_claims"] > 0),
    })


def tables() -> dict[str, pd.DataFrame]:
    """reporting.claims_ss_summary, _cube, _slices, _hail, _channel_quarterly, _metrics (empty if no results)."""
    if not (SUMMARY.exists() and CUBE.exists()):
        return {}
    s = json.loads(SUMMARY.read_text(encoding="utf-8"))
    h = s["headline"]
    hail = pd.DataFrame(s["hail"]["homeowners_by_month"])
    hail["claims_reported"] = hail["claims_reported"].fillna(0).astype(int)
    hail["is_hail_month"] = hail["month"] == s["hail"]["month"]
    hail["month"] = pd.to_datetime(hail["month"]).dt.date
    storm = hail[hail["is_hail_month"]].iloc[0]
    others = hail[~hail["is_hail_month"]]

    by = {k: {r[k]: r for r in rows} for k, rows in s["by"].items()}
    cube = pd.read_csv(CUBE)
    # the whole-book ratios from the summed parts, unrounded, so the headline and the unfiltered drill-down agree
    whole = ratios(cube.sum(numeric_only=True).to_frame().T).iloc[0]
    summary = pd.DataFrame([{
        "as_of": pd.Timestamp(s["as_of"]).date(), "policies": s["policies"], "claims": s["claims"],
        **{f"claims_{k}": v for k, v in s["claims_by_status"].items()},
        **{m: whole[m] for m in ("loss_ratio", "claim_cycle_time_days", "approval_rate")},
        "earned_premium": h["earned_premium"],
        "incurred_losses": h["incurred_losses"], "n_metrics": len(s["metrics"]),
        "hail_region": _label(s["hail"]["region"]), "hail_month": s["hail"]["month"],
        "hail_month_label": pd.Timestamp(s["hail"]["month"]).strftime("%B %Y"),
        "hail_loss_ratio": storm["loss_ratio"], "hail_claims": int(storm["claims_reported"]),
        "other_months_min_claims": int(others["claims_reported"].min()),
        "other_months_max_claims": int(others["claims_reported"].max()),
        "south_loss_ratio": by["region"]["south"]["loss_ratio"],
        "direct_approval_rate": by["channel"]["direct"]["approval_rate"],
        "agent_approval_rate": by["channel"]["agent"]["approval_rate"],
        "broker_approval_rate": by["channel"]["broker"]["approval_rate"],
    }])

    cube["month"] = pd.to_datetime(cube["month"]).dt.date
    for col in ("line_of_business", "region", "channel"):
        cube[f"{col}_label"] = cube[col].map(_label)

    slices = pd.DataFrame([
        {"slice_sort": i, "slice": SLICE_LABELS[k], "value": r[k], "value_label": _label(r[k]),
         **{m: r.get(m) for m in ("loss_ratio", "claim_cycle_time_days", "approval_rate")}}
        for i, (k, rows) in enumerate(s["by"].items()) for r in rows])

    # direct-channel denials over time: decided claims by channel and close quarter, from the cube
    q = cube.assign(quarter=pd.to_datetime(cube["month"]).dt.to_period("Q").astype(str))
    q = q.groupby(["quarter", "channel", "channel_label"], as_index=False)[["approved_claims", "decided_claims"]].sum()
    q = q[q["decided_claims"] > 0]
    q["quarter_start"] = pd.PeriodIndex(q["quarter"], freq="Q").start_time.date
    q["denied_claims"] = q["decided_claims"] - q["approved_claims"]
    q["approval_rate"] = q["approved_claims"] / q["decided_claims"]
    q["denial_rate"] = 1 - q["approval_rate"]

    defs = yaml.safe_load(METRICS_YML.read_text(encoding="utf-8"))["metrics"]
    metric_rows = []
    for i, m in enumerate(defs):
        tp = m["type_params"]
        ratio = m["type"] == "ratio"
        metric_rows.append({
            "sort": i, "name": m["name"], "label": m["label"], "type": m["type"],
            "computed_as": f"{tp['numerator']} / {tp['denominator']}" if ratio else f"sum of {tp['measure']}",
            "description": " ".join(m["description"].split()), "not_fit_for": NOT_FIT_FOR.get(m["name"], ""),
            "whole_book": h.get(m["name"]),
        })

    return {"claims_ss_summary": summary, "claims_ss_cube": cube, "claims_ss_slices": slices,
            "claims_ss_hail": hail, "claims_ss_channel_quarterly": q.reset_index(drop=True),
            "claims_ss_metrics": pd.DataFrame(metric_rows)}
