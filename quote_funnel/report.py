"""The quote funnel's dashboard tables, from its committed results (no warehouse needed).

`python -m quote_funnel` writes results/summary.json and results/funnel_weekly.csv;
scripts/export_reporting.py turns them into reporting.quote_funnel_* tables for the Evidence page.
The funnel is a separate simulated project, so its numbers are fixed and do not move with the nightly build.
"""
import json
from pathlib import Path

import pandas as pd

RESULTS_DIR = Path(__file__).resolve().parent / "results"
SUMMARY = RESULTS_DIR / "summary.json"
WEEKLY = RESULTS_DIR / "funnel_weekly.csv"
MEMO_URL = "https://github.com/sky-five/ridgeline-analytics/blob/main/quote_funnel/results/memo.md"

SEGMENT_LABELS = {"auto_standard": "Auto, standard", "auto_non_standard": "Auto, non-standard",
                  "home_standard": "Home, standard", "home_non_standard": "Home, non-standard"}
SEGMENT_ORDER = list(SEGMENT_LABELS)


def tables() -> dict[str, pd.DataFrame]:
    """reporting.quote_funnel_summary, _weekly, _segments and _carrier, or nothing if results are missing."""
    if not (SUMMARY.exists() and WEEKLY.exists()):
        return {}
    s = json.loads(SUMMARY.read_text(encoding="utf-8"))
    cc, nc = s["counting_change"], s["new_carrier"]
    brk = cc["logging_break"]
    est, truth = nc["estimate"], nc["truth"]
    per_req, per_ses = cc["quote_to_bind_per_request"], cc["quote_to_bind_per_session"]

    summary = pd.DataFrame([{
        **{k: s["source_rows"][k] for k in ("sessions", "quote_requests", "carrier_quotes", "clicks", "binds")},
        **{k: s["funnel"][k] for k in ("quote_rate", "click_rate", "bind_rate", "quote_to_bind", "commission")},
        "break_week": pd.Timestamp(brk["week"]).date(),
        "true_break_week": pd.Timestamp(s["true_logging_change"]).date(),
        "requests_per_session_before": brk["requests_per_session_before"],
        "requests_per_session_after": brk["requests_per_session_after"],
        # rates as fractions so the page can format them like the others; the summary keeps percentage points
        "per_request_before": per_req["before"], "per_request_after": per_req["after"],
        "per_request_diff": per_req["diff_pp"] / 100, "per_request_p": per_req["p_value"],
        "per_session_before": per_ses["before"], "per_session_after": per_ses["after"],
        "per_session_diff": per_ses["diff_pp"] / 100,
        "per_session_ci_low": per_ses["ci_pp"][0] / 100, "per_session_ci_high": per_ses["ci_pp"][1] / 100,
        "per_session_p": per_ses["p_value"],
        "relative_drop_per_request": cc["relative_drop_per_request_pct"] / 100,
        "share_of_drop_from_request_count": cc["share_of_drop_from_request_count_pct"] / 100,
        "memo_url": MEMO_URL,
    }])

    weekly = pd.read_csv(WEEKLY, parse_dates=["week"])
    weekly["week"] = weekly["week"].dt.date
    weekly["after_break"] = weekly["week"] >= summary.loc[0, "break_week"]

    segments = pd.DataFrame(s["by_segment"])
    segments["segment_label"] = segments["segment"].map(SEGMENT_LABELS)
    segments["sort"] = segments["segment"].map(SEGMENT_ORDER.index)
    segments = segments.sort_values("sort").reset_index(drop=True)

    carrier = pd.DataFrame([
        {"sort": 0, "measure": "Added binds", "unit": "binds", "estimate": est["added_binds"],
         "ci_low": est["added_binds_ci"][0], "ci_high": est["added_binds_ci"][1], "truth": truth["added_binds"]},
        {"sort": 1, "measure": "Added commission", "unit": "usd", "estimate": est["added_commission"],
         "ci_low": est["added_commission_ci"][0], "ci_high": est["added_commission_ci"][1],
         "truth": truth["added_commission"]},
        {"sort": 2, "measure": "Policies the candidate writes", "unit": "binds", "estimate": est["candidate_binds"],
         "ci_low": None, "ci_high": None, "truth": truth["candidate_binds"]},
    ])
    covers = (carrier["ci_low"] <= carrier["truth"]) & (carrier["truth"] <= carrier["ci_high"])
    carrier["ci_covers"] = covers.astype("boolean").where(carrier["ci_low"].notna())  # no interval, no verdict
    for k in ("sample_sessions", "sample_quoted_by_candidate", "auto_sessions"):
        carrier[k] = est[k]
    carrier["onboarding_cost_assumed"] = nc["onboarding_cost_assumed"]
    carrier["payback_months"] = nc["payback_months"]

    lost = pd.DataFrame([
        {"carrier": c, "source": src, "binds_lost": vals[c]}
        for src, vals in (("Estimate", est["lost_by_panel"]), ("Replayed truth", truth["lost_by_panel"]))
        for c in sorted(vals)])

    return {"quote_funnel_summary": summary, "quote_funnel_weekly": weekly,
            "quote_funnel_segments": segments, "quote_funnel_carrier": carrier,
            "quote_funnel_lost_binds": lost}
