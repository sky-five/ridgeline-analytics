"""The reconciliation kit's dashboard tables, from its committed results (no warehouse needed).

`python -m report_reconciliation` writes results/summary.json; scripts/export_reporting.py turns it into
reporting.recon_* tables for the Evidence page. The kit runs on its own seeded data, so these numbers are fixed
and do not move with the nightly build.
"""
import json
from pathlib import Path

import pandas as pd

from report_reconciliation import uat
from report_reconciliation.build import FAULTS

SUMMARY = Path(__file__).resolve().parent / "results" / "summary.json"
CHECKS = ("row_count", "totals", "refresh_age", "lineage")
FAULT_TEXT = {
    "rate_join_fan_out": "Rates joined on person only, so people with a raise are counted twice",
    "rejected_included": "The approved-only filter is dropped",
    "closed_projects_dropped": "An inner join to active projects drops closed ones",
    "stale_extract": "The timesheet extract is 30 hours old",
    "undocumented_column": "A new mart column with no lineage entry",
}


def tables(summary_path: Path = SUMMARY) -> dict[str, pd.DataFrame]:
    """reporting.recon_summary, recon_checks, recon_faults, recon_uat and recon_samples, or nothing if the
    results are missing."""
    if not summary_path.exists():
        return {}
    s = json.loads(summary_path.read_text(encoding="utf-8"))
    reports = s["reports"]
    title = {r["report"]: r["title"] for r in reports}
    order = {r["report"]: i for i, r in enumerate(reports)}

    checks = pd.DataFrame([
        {"report_sort": order[r["report"]], "check_sort": CHECKS.index(k), "report": r["report"],
         "title": r["title"], "mart": r["mart"], "check_name": k, "ok": c["ok"],
         "status": "pass" if c["ok"] else "fail", "detail": uat.CHECK_TEXT[k](c)}
        for r in reports for k, c in r["checks"].items()])

    faults = pd.DataFrame([
        {"fault_sort": FAULTS.index(f), "report_sort": order[rep], "fault": f, "what": FAULT_TEXT[f],
         "report": rep, "title": title[rep], "failed_checks": ", ".join(failed) or "all pass",
         "caught": bool(failed), **{f"fails_{k}": k in failed for k in CHECKS}}
        for f, by_report in s["planted_faults"].items() for rep, failed in by_report.items()])

    uat_rows = []
    for r in reports:
        items = [("automated", uat.CHECK_TEXT[k](c), c["ok"], "the checks") for k, c in r["checks"].items()]
        items += [("owner", item, who is not None, who or "needs the report owner")
                  for item, who in uat.SIGN_OFF[r["report"]].items()]
        uat_rows += [{"report_sort": order[r["report"]], "item_sort": i, "report": r["report"],
                      "title": r["title"], "kind": kind, "item": item, "done": done, "who": who,
                      "definitions": uat.DEFINITIONS[r["report"]]}
                     for i, (kind, item, done, who) in enumerate(items)]
    uat_table = pd.DataFrame(uat_rows)

    samples = []
    for rep, rows in s["samples"].items():
        for i, row in enumerate(rows):
            *keys, measure = row
            samples.append({"report_sort": order[rep], "row_sort": i, "report": rep, "title": title[rep],
                            "row_key": ", ".join(str(row[k]) for k in keys), "measure": measure,
                            "value": row[measure]})

    hours = reports[0]["checks"]["totals"]["measures"]
    summary = pd.DataFrame([{
        "as_of": s["as_of"], "built_at": s["built_at"], "reports": len(reports),
        "reports_passing": sum(r["ok"] for r in reports),
        "checks": len(checks), "checks_passing": int(checks["ok"].sum()),
        "faults": len(s["planted_faults"]),
        "faults_caught": sum(any(v.values()) for v in s["planted_faults"].values()),
        "owner_items_open": int((~uat_table["done"] & (uat_table["kind"] == "owner")).sum()),
        "timesheet_entries": s["source_rows"]["timesheets"], "approved_entries": s["timesheet_status"]["approved"],
        "approved_hours": hours["hours"]["source"], "approved_cost": hours["cost"]["source"],
    }])
    return {"recon_summary": summary, "recon_checks": checks, "recon_faults": faults, "recon_uat": uat_table,
            "recon_samples": pd.DataFrame(samples)}
