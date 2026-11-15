"""The ED wait-times dashboard tables, from the committed results and the pinned public file (no warehouse needed).

`python -m ed_wait_times` writes results/summary.json and results/site_week.csv; scripts/export_reporting.py turns
them into reporting.ed_* tables for the Evidence page. The sites are a separate simulated project, so the numbers
are fixed and do not move with the nightly build.
"""
import json

import pandas as pd

from ed_wait_times import public
from ed_wait_times.run import SITE_WEEK, SUMMARY
from ed_wait_times.simulate import CLOSED_BEDS, SMALL_SITE, site_frame

GROUP_LABELS = {
    "admitted": "Admitted",
    "high_urgency_sent_home": "Sent home, high urgency (levels 1-3)",
    "low_urgency_sent_home": "Sent home, low urgency (levels 4-5)",
}


def _date(v):
    return pd.Timestamp(v).date() if v else None


def tables() -> dict[str, pd.DataFrame]:
    """reporting.ed_summary, _last_week, _sites, _site_week, _throughput_weekly, _icu_daily, _icu_odd_days
    (empty if there are no results)."""
    if not (SUMMARY.exists() and SITE_WEEK.exists()):
        return {}
    s = json.loads(SUMMARY.read_text(encoding="utf-8"))
    sim, last, closure, icu = s["simulated"], s["last_week"], s["bed_closure"], s["public_icu"]
    sites = site_frame()

    w = pd.read_csv(SITE_WEEK)
    w["week_start"] = pd.to_datetime(w["week_start"]).dt.date
    w = w.merge(sites, on="site_id", how="left")
    w["group_label"] = w["patient_group"].map(GROUP_LABELS)
    # an unreported week has no 90th percentile to show: too few patients, not a pass
    w["p90_reported_hours"] = w["p90_los_hours"].where(w["reportable"])

    by_week = w.groupby(["site_id", "site_type", "region", "week_start"], as_index=False).agg(
        visits=("patients", "sum"), mean_bed_occupancy=("mean_bed_occupancy", "first"),
        staffed_beds=("min_staffed_beds", "first"))
    admitted = w[w["patient_group"] == "admitted"].set_index(["site_id", "week_start"])
    by_week = by_week.join(
        admitted[["patients", "p90_reported_hours", "breached", "reportable"]].rename(
            columns={"patients": "admitted", "p90_reported_hours": "admitted_p90_hours"}),
        on=["site_id", "week_start"])
    by_week["share_admitted"] = by_week["admitted"] / by_week["visits"]

    lw = pd.DataFrame(last["sites"])
    lw["status"] = [("over target" if b else "within target") if r else "not reported (under 20 patients)"
                    for r, b in zip(lw["reported"], lw["breached"], strict=True)]
    lw["p90_reported_hours"] = lw["p90_hours"].where(lw["reported"])
    lw.insert(0, "sort", range(len(lw)))

    per_site = pd.DataFrame(s["admitted_weeks_by_site"]).merge(sites, on="site_id", how="left")
    totals = by_week.groupby("site_id", as_index=False).agg(visits=("visits", "sum"), admitted=("admitted", "sum"))
    per_site = per_site.merge(totals, on="site_id")

    raw = public.read()
    odd = pd.DataFrame(icu["odd_days"])
    odd["date"] = pd.to_datetime(odd["date"]).dt.date
    odd["why"] = [
        "; ".join(([f"{a:,} adult patients, far from the median of the week around it"] if o else [])
                  + ([f"{a:,} adult patients for {ab:,} adult beds"] if a > ab else [])
                  + ([f"{p} paediatric patients for {pb} paediatric beds"] if p > pb else []))
        for a, ab, p, pb, o in zip(odd["adult_patients"], odd["adult_beds"], odd["ped_patients"], odd["ped_beds"],
                                   odd["adult_patients_outlier"], strict=True)]
    daily = pd.DataFrame({
        "census_date": raw["date"].dt.date,
        "adult_patients": raw["total_adult_icu_patients"], "adult_beds": raw["total_adult_icu_beds"],
        "adult_occupancy": raw["total_adult_icu_patients"] / raw["total_adult_icu_beds"],
        "ped_patients": raw["total_ped_icu_patients"], "ped_beds": raw["total_ped_icu_beds"],
        "ped_occupancy": raw["total_ped_icu_patients"] / raw["total_ped_icu_beds"],
    })
    daily["odd_day"] = daily["census_date"].isin(set(odd["date"]))

    before, after = closure["before"], closure["after"]
    summary = pd.DataFrame([{
        "first_day": _date(sim["first_day"]), "last_day": _date(sim["last_day"]), "sites": sim["sites"],
        "visits": sim["visits"], "admitted": sim["admitted"], "p90_admitted_hours_all": sim["p90_admitted_hours_all"],
        "target_hours": last["target_hours"], "week_start": _date(last["week_start"]),
        "week_end": _date(last["week_end"]), "breached_last_week": len(last["breached"]),
        "breached_sites": ", ".join(last["breached"]), "not_reported_sites": ", ".join(last["not_reported"]),
        "closure_site": closure["site_id"], "closure_from": _date(closure["from"]), "closed_beds": CLOSED_BEDS,
        "closure_before_weeks": before["weeks"], "closure_before_breached": before["breached_weeks"],
        "closure_before_p90": before["median_p90_hours"], "closure_before_occupancy": before["mean_bed_occupancy"],
        "closure_after_weeks": after["weeks"], "closure_after_breached": after["breached_weeks"],
        "closure_after_p90": after["median_p90_hours"], "closure_after_occupancy": after["mean_bed_occupancy"],
        "small_site": SMALL_SITE,
        "small_site_unreported_weeks": int(per_site.set_index("site_id").loc[SMALL_SITE, "unreported_weeks"]),
        "weeks": int(per_site["weeks"].max()),
        "icu_first_day": _date(icu["first_day"]), "icu_last_day": _date(icu["last_day"]), "icu_days": icu["days"],
        "icu_median_adult_occupancy": icu["median_adult_occupancy"], "icu_odd_days": len(odd),
        "icu_licence": icu["licence"], "icu_source": icu["source"],
    }])

    return {
        "ed_summary": summary, "ed_last_week": lw, "ed_sites": per_site, "ed_site_week": w,
        "ed_throughput_weekly": by_week, "ed_icu_daily": daily, "ed_icu_odd_days": odd,
    }
