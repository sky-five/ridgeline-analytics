"""The onboarding funnel dashboard tables, from the committed results (no warehouse needed).

`python -m onboarding_funnel` writes results/summary.json and results/funnel_weekly.csv;
scripts/export_reporting.py turns them into reporting.onb_* tables for the Evidence page.
The event log is a separate simulated project, so its numbers are fixed and do not move with the nightly build.
"""
import json

import pandas as pd

from onboarding_funnel.run import SUMMARY, WEEKLY

PROGRAM_LABELS = {
    "consumer_card": "Consumer card", "gig_payouts": "Gig payouts",
    "business_expense": "Business expense", "cross_border": "Cross-border",
}
# funnel steps in order, with the column in summary.json["funnel"] that counts people reaching each one
STEPS = [
    ("started", "Started"), ("uploaded", "Uploaded a document"), ("submitted", "Submitted"),
    ("kyc_passed", "Passed KYC"), ("funded", "Funded"), ("activated", "First transaction in 30 days"),
]
STEP_LABELS = {
    "document_upload": "Document upload", "submit": "Submit", "kyc": "KYC", "funding": "Funding",
    "first_transaction": "First transaction",
}
RATE_LABELS = {
    "activation_rate_per_id": "Activation per application id", "activation_rate": "Activation per person",
    "kyc_pass_rate": "KYC pass rate",
}


def _program(v: str) -> str:
    return PROGRAM_LABELS.get(v, v)


def _reason(v: str) -> str:
    return v.replace("_", " ").capitalize()


def _date(v):
    return pd.Timestamp(v).date() if v else None


def tables() -> dict[str, pd.DataFrame]:
    """reporting.onb_summary, _funnel, _drop_offs, _time_to_first_txn, _weekly, _activation_weekly, _checks,
    _steps (empty if there are no results)."""
    if not (SUMMARY.exists() and WEEKLY.exists()):
        return {}
    s = json.loads(SUMMARY.read_text(encoding="utf-8"))
    c = s["checks"]
    brk = s["counting_breaks"][0]
    real = next(x for x in s["steps"] if x.get("reading") == "real")
    shift = s["kyc_reason_shifts"][0]
    noise = max((x for x in s["steps"] if not x["shift"]), key=lambda x: abs(x["t"]))
    ipp = c["ids_per_person"]

    funnel_rows = []
    for f in s["funnel"]:
        for i, (col, label) in enumerate(STEPS):
            prev = f[STEPS[i - 1][0]] if i else f["started"]
            funnel_rows.append({
                "program": f["program"], "program_label": _program(f["program"]), "step_sort": i,
                "step": label, "people": f[col], "share_of_started": f[col] / f["started"],
                "share_of_previous_step": f[col] / prev,
            })
    funnel = pd.DataFrame(funnel_rows)
    by_program = pd.DataFrame(s["funnel"]).set_index("program")

    summary = pd.DataFrame([{
        "as_of": _date(s["as_of"]), "first_week": _date(s["first_week"]),
        "last_mature_week": _date(s["last_mature_week"]),
        "people": c["person_key"]["true_people"], "application_ids": c["person_key"]["application_ids"],
        "delivered_events": c["redelivery"]["delivered_rows"], "redelivered": c["redelivery"]["redelivered"],
        "raw_email_split": c["person_key"]["raw_email_key"]["people_split"],
        "mature_started": int(by_program["started"].sum()),
        "mature_activation_rate": by_program["activated"].sum() / by_program["started"].sum(),
        "ids_limit": ipp["limit"],
        "break_program_label": _program(brk["program"]), "break_week": _date(brk["from_week"]),
        "break_max_ids_per_person": ipp["programs"][brk["program"]]["max"],
        "break_weeks_over": ipp["programs"][brk["program"]]["weeks_over_limit"],
        "per_id_before": brk["per_application_id"]["before"], "per_id_after": brk["per_application_id"]["after"],
        "per_id_change_pp": brk["per_application_id"]["change_pp"],
        "per_id_ci_low": brk["per_application_id"]["ci_pp"][0],
        "per_id_ci_high": brk["per_application_id"]["ci_pp"][1],
        "per_person_before": brk["per_person"]["before"], "per_person_after": brk["per_person"]["after"],
        "per_person_change_pp": brk["per_person"]["change_pp"],
        "per_person_ci_low": brk["per_person"]["ci_pp"][0], "per_person_ci_high": brk["per_person"]["ci_pp"][1],
        "share_from_counting": brk["share_of_drop_from_counting"],
        "real_program_label": _program(real["program"]), "real_week": _date(real["week"]),
        "real_before": real["before"], "real_after": real["after"], "real_t": real["t"],
        "real_reason": _reason(shift["reason"]), "real_reason_before": shift["before"],
        "real_reason_after": shift["after"],
        "noise_t": noise["t"], "noise_label": f"{_program(noise['program'])}, {RATE_LABELS[noise['rate']]}",
    }])

    drops = pd.DataFrame(s["drop_off_reasons"])
    drops["program_label"] = drops["program"].map(_program)
    drops["step_label"] = drops["drop_off_step"].map(STEP_LABELS)
    drops["reason_label"] = drops["drop_off_reason"].map(_reason)

    ttft = pd.DataFrame(s["time_to_first_transaction"])
    ttft["program_label"] = ttft["program"].map(_program)

    w = pd.read_csv(WEEKLY)
    w["cohort_week"] = pd.to_datetime(w["cohort_week"]).dt.date
    w["program_label"] = w["program"].map(_program)
    w["is_mature"] = w["is_mature"].astype(bool)
    w["over_limit"] = w["application_ids_per_applicant"] > ipp["limit"]

    # the counting break, both ways of counting on one chart (long form, mature weeks only)
    m = w[w["is_mature"]]
    activation = pd.concat([
        m.assign(counted="Per application id", activation=m["activation_rate_per_id"]),
        m.assign(counted="Per person", activation=m["activation_rate"]),
    ])[["program", "program_label", "cohort_week", "counted", "activation"]]

    pk = c["person_key"]
    checks = pd.DataFrame([
        {"sort": 0, "check": "Redeliveries counted once", "passed": c["redelivery"]["passed"],
         "result": f"{c['redelivery']['redelivered']:,} of {c['redelivery']['delivered_rows']:,} delivered rows "
                   f"repeat an event id; {c['redelivery']['copies_that_differ']} copies differ; "
                   f"{c['redelivery']['staged']:,} staged"},
        {"sort": 1, "check": "Person key against the simulator's labels", "passed": pk["passed"],
         "result": f"{pk['application_ids']:,} application ids, {pk['true_people']:,} people, "
                   f"{pk['applications']:,} applications found; splits {pk['normalised_key']['people_split']}, "
                   f"merges {pk['normalised_key']['people_merged']} (raw email would split "
                   f"{pk['raw_email_key']['people_split']})"},
        {"sort": 2, "check": f"Application ids per person at most {ipp['limit']}", "passed": ipp["passed"],
         "result": "; ".join(
             f"{_program(p)} over from {v['first_week_over']} for {v['weeks_over_limit']} weeks (max {v['max']})"
             for p, v in ipp["programs"].items() if v["weeks_over_limit"]) or "every program within the limit"},
    ])

    steps = pd.DataFrame(s["steps"])
    steps["program_label"] = steps["program"].map(_program)
    steps["rate_label"] = steps["rate"].map(RATE_LABELS)
    steps["week"] = pd.to_datetime(steps["week"]).dt.date
    steps["reading"] = steps.get("reading", pd.Series(dtype=object)).fillna("no shift")

    return {"onb_summary": summary, "onb_funnel": funnel, "onb_drop_offs": drops, "onb_time_to_first_txn": ttft,
            "onb_weekly": w, "onb_activation_weekly": activation.reset_index(drop=True), "onb_checks": checks,
            "onb_steps": steps}
