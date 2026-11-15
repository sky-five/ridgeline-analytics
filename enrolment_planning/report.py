"""The enrolment planning dashboard tables, from the committed results only (no warehouse needed).

`python -m enrolment_planning` writes results/; scripts/export_reporting.py turns them into reporting.enrol_* tables
for the Evidence page. The data is public and pinned, so the numbers are fixed and do not move with the nightly
build.

The what-if turns a year of new post-secondary study permits (October to September) into a fall count of
international enrolments: intake times enrolments per new permit. The ratio is a stock over a flow (the fall count
holds every year of study, the permits only the new arrivals), so it rises when intake falls; the page offers the
published years' ratios rather than one number.
"""
import json

import pandas as pd

from enrolment_planning.run import PERMITS_MONTHLY, SCORES, SHARE, SUMMARY

SERIES_NAMES = {"CA": "Canada", "ON": "Ontario", "BC": "British Columbia", "QC": "Quebec", "AB": "Alberta"}
REGION_NAMES = {
    "CA": "Canada", "NL": "Newfoundland and Labrador", "PE": "Prince Edward Island", "NS": "Nova Scotia",
    "NB": "New Brunswick", "QC": "Quebec", "ON": "Ontario", "MB": "Manitoba", "SK": "Saskatchewan",
    "AB": "Alberta", "BC": "British Columbia", "TR": "Territories",
}
RULE_LABELS = {
    "same_month_last_year": "Same month last year",
    "last_year_with_trend": "Last year with trend",
    "three_year_mean": "Three-year mean",
}
GROUP_LABELS = {"ALL": "All programs", "STEM": "STEM", "BHASE": "BHASE", "Unclassified": "Unclassified"}


def intake_window(monthly: pd.DataFrame, fall_year: int) -> int | None:
    """Canada's new post-secondary permits from October of fall_year - 1 to September of fall_year (None if any
    month is not published yet)."""
    ca = monthly[monthly["series"] == "CA"].set_index("month")["permits"]
    months = [str(m) for m in pd.period_range(f"{fall_year - 1}-10", f"{fall_year}-09", freq="M")]
    return int(ca[months].sum()) if all(m in ca.index for m in months) else None


def ratio_choices(bridge: pd.DataFrame) -> pd.DataFrame:
    """The ratios the what-if offers: the last published fall, the lowest, the mean and the highest."""
    last = bridge.iloc[-1]
    low = bridge.loc[bridge["enrolments_per_new_permit"].idxmin()]
    high = bridge.loc[bridge["enrolments_per_new_permit"].idxmax()]
    mean = round(float(bridge["enrolments_per_new_permit"].mean()), 3)
    first, final = int(bridge["fall_year"].min()), int(bridge["fall_year"].max())
    rows = [
        ("last", f"As in fall {int(last.fall_year)}", last.enrolments_per_new_permit),
        ("low", f"Lowest (fall {int(low.fall_year)})", low.enrolments_per_new_permit),
        ("mean", f"Mean of falls {first}-{final}", mean),
        ("high", f"Highest (fall {int(high.fall_year)})", high.enrolments_per_new_permit),
    ]
    # a text key for the page's dropdown: Evidence matches a dropdown's default by value, which a float may miss
    return pd.DataFrame([{"sort": i, "ratio_key": key, "choice": f"{label}: {r:.2f}", "ratio": float(r)}
                         for i, (key, label, r) in enumerate(rows)])


def tables() -> dict[str, pd.DataFrame]:
    """reporting.enrol_summary, _share, _backtest, _backtest_horizon, _permits_monthly, _bridge, _ratios
    (empty if there are no results)."""
    if not all(p.exists() for p in (SUMMARY, SCORES, SHARE, PERMITS_MONTHLY)):
        return {}
    s = json.loads(SUMMARY.read_text(encoding="utf-8"))
    e, src, bt = s["enrolments"], s["sources"], s["backtest"]

    share = pd.read_csv(SHARE)
    share.insert(1, "fall", share["fall_year"].astype(str))  # a label: the site's charts treat numbers as values
    share.insert(3, "region_name", share["region_code"].map(REGION_NAMES))
    share["group_label"] = share["program_group"].map(GROUP_LABELS)

    scores = pd.read_csv(SCORES)
    scores["series_name"] = scores["series"].map(SERIES_NAMES)
    scores["rule_label"] = scores["rule"].map(RULE_LABELS)
    backtest = scores[scores["measure"] == "next_12_months"].drop(columns=["measure", "horizon"])
    best = backtest.groupby(["series", "period"])["wape"].transform("min")
    backtest = backtest.assign(is_best=backtest["wape"] == best).reset_index(drop=True)
    horizon = scores[scores["measure"] == "month"].drop(columns=["measure"]).reset_index(drop=True)

    monthly = pd.read_csv(PERMITS_MONTHLY, dtype={"month": str})
    permits = monthly.assign(month=pd.to_datetime(monthly["month"]).dt.date,
                             series_name=monthly["series"].map(SERIES_NAMES))

    bridge = pd.DataFrame(s["intake_to_enrolment"])
    bridge.insert(1, "fall", bridge["fall_year"].astype(str))
    ratios = ratio_choices(bridge)
    next_fall = int(bridge["fall_year"].max()) + 1
    next_intake = intake_window(monthly, next_fall)
    last_month = src["study_permits"]["last_month"]
    trailing = int(monthly[monthly["series"] == "CA"].tail(12)["permits"].sum())

    summary = pd.DataFrame([{
        "last_fall": e["last_fall"], "total": e["total"], "international": e["international"],
        "international_share": e["international_share"], "peak_international_fall": e["peak_international_fall"],
        "peak_international": e["peak_international"], "first_fall": src["enrolments"]["first_fall"],
        "first_fall_international_share": e["first_fall_international_share"],
        "fact_rows": src["enrolments"]["fact_rows"], "cells_not_published": src["enrolments"]["cells_not_published"],
        "permit_first_month": src["study_permits"]["first_month"], "permit_last_month": last_month,
        "permit_cells": src["study_permits"]["cells"],
        "permit_cells_suppressed": src["study_permits"]["cells_suppressed"],
        "backtest_first_origin": bt["first_origin"], "backtest_last_origin": bt["last_origin"],
        "monthly_forecasts": bt["monthly_forecasts"],
        "last_bridge_fall": int(bridge["fall_year"].max()),
        "last_bridge_intake": int(bridge["new_permits_oct_to_sep"].iloc[-1]),
        "next_fall": next_fall, "next_fall_intake": next_intake,
        "trailing_12_months_permits": trailing, "ratio_low": float(ratios["ratio"].min()),
        "ratio_high": float(ratios["ratio"].max()), "licence": src["enrolments"]["licence"],
        "statcan_table": src["enrolments"]["table"], "ircc_dataset": src["study_permits"]["dataset"],
    }])

    return {
        "enrol_summary": summary, "enrol_share": share, "enrol_backtest": backtest,
        "enrol_backtest_horizon": horizon, "enrol_permits_monthly": permits, "enrol_bridge": bridge,
        "enrol_ratios": ratios,
    }
