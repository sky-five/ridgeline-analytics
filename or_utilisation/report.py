"""The operating-room ROI dashboard tables, from the committed results and metric_spec.yml (no warehouse needed).

`python -m or_utilisation` writes results/summary.json and results/utilisation_weekly.csv;
scripts/export_reporting.py turns them into reporting.or_roi_* tables for the Evidence page.
The suite is a separate simulated project, so its numbers are fixed and do not move with the nightly build.
"""
import json
from pathlib import Path

import pandas as pd

from or_utilisation import spec

RESULTS_DIR = Path(__file__).resolve().parent / "results"
SUMMARY = RESULTS_DIR / "summary.json"
WEEKLY = RESULTS_DIR / "utilisation_weekly.csv"

FRAMINGS = [  # (key in summary["roi"], label, how it is computed)
    ("claimed", "Claimed", "Change in adjusted block utilisation x all block minutes"),
    ("before_after", "Before/after", "Change in room utilisation x all block minutes"),
    ("defended", "Defended", "Other services' minutes in released blocks above the before-period rate"),
]
CHECK_LABELS = {
    "denominator_moved": "Denominator moved",
    "counts_turnover": "Counts turnover as use",
    "misses_the_gain": "Misses the rule's gain",
    "moved_where_rule_cannot_act": "Moved on blocks the rule cannot touch",
    "unequal_windows": "Unequal windows",
}


def tables() -> dict[str, pd.DataFrame]:
    """reporting.or_roi_summary, _framings, _claims, _checks, _weekly, _metric_spec (empty if no results)."""
    if not (SUMMARY.exists() and WEEKLY.exists()):
        return {}
    s = json.loads(SUMMARY.read_text(encoding="utf-8"))
    r, a = s["roi"], s["assumptions"]
    policy_start = pd.Timestamp(s["policy_start"]).date()

    summary = pd.DataFrame([{
        "policy_start": policy_start,
        **{k: s[k] for k in ("rooms", "block_days", "blocks", "releases", "auto_releases",
                             "cases_booked", "cases_completed")},
        **{f"{k}_minutes": r[k]["added_minutes"] for k, _, _ in FRAMINGS},
        **{f"{k}_net_usd": r[k]["net_usd"] for k, _, _ in FRAMINGS},
        "defended_ci_low": r["defended"]["ci_low"], "defended_ci_high": r["defended"]["ci_high"],
        "true_minutes": r["true_added_minutes"], "true_net_usd": r["true_net_usd"],
        "true_cases": s["truth"]["added_completed_cases"],
        "defended_ci_covers_truth": r["defended_ci_covers_truth"],
        "claimed_over_truth": r["claimed_over_truth"],
        "margin_per_patient_hour_usd": a["margin_per_patient_hour_usd"], "rule_cost_usd": a["rule_cost_usd"],
    }])

    framings = pd.DataFrame(
        [{"sort": i, "framing": label, "method": method, "added_minutes": r[k]["added_minutes"],
          "ci_low": r[k]["ci_low"], "ci_high": r[k]["ci_high"], "net_usd": r[k]["net_usd"]}
         for i, (k, label, method) in enumerate(FRAMINGS)]
        + [{"sort": len(FRAMINGS), "framing": "Replayed truth", "method": "Same half-year simulated with the rule off",
            "added_minutes": r["true_added_minutes"], "ci_low": None, "ci_high": None, "net_usd": r["true_net_usd"]}])
    framings["over_truth"] = (framings["added_minutes"] / r["true_added_minutes"]).round(2)

    metrics = spec.metrics()
    claims = pd.DataFrame([{
        "sort": i, "metric": c["metric"], "metric_label": metrics[c["metric"]]["label"],
        "before": c["before"], "after": c["after"], "change_pp": c["change_pp"],
        "n_flags": len(c["flags"]), "flags": ", ".join(CHECK_LABELS[f].lower() for f in c["flags"]) or "none",
    } for i, c in enumerate(s["claims"])])

    checks = pd.DataFrame([{
        "claim_sort": i, "check_sort": j, "metric_label": metrics[c["metric"]]["label"], "check_name": k["check"],
        "check_label": CHECK_LABELS[k["check"]], "flagged": k["flagged"],
        "result": "flagged" if k["flagged"] else "passes",
        "size_pp": k["size_pp"], "detail": k["detail"],
    } for i, c in enumerate(s["claims"]) for j, k in enumerate(c["checks"])])

    weekly = pd.read_csv(WEEKLY, parse_dates=["block_week"])
    weekly["block_week"] = weekly["block_week"].dt.date
    weekly["after_rule"] = weekly["block_week"] >= policy_start

    before, after = s["periods"]["before_all"], s["periods"]["after_all"]
    metric_spec = pd.DataFrame([{
        "sort": i, "metric": name, "label": m["label"], "numerator": m["numerator"],
        "denominator": m["denominator"], "definition": m["definition"], "fit_for": m["fit_for"],
        "includes_turnover": m["includes_turnover"],
        "denominator_excludes_released_time": m["denominator_excludes_released_time"],
        "before": before.get(name), "after": after.get(name),
        "before_text": f"{before[name]:.1%}", "after_text": f"{after[name]:.1%}",  # for the page's text panels
    } for i, (name, m) in enumerate(metrics.items())])

    return {"or_roi_summary": summary, "or_roi_framings": framings, "or_roi_claims": claims,
            "or_roi_checks": checks, "or_roi_weekly": weekly, "or_roi_metric_spec": metric_spec}
