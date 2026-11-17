"""The lead-cost dashboard tables, from the committed results only (no warehouse needed).

`python -m lead_cost` writes results/; scripts/export_reporting.py turns them into reporting.lead_cost_* tables for
the Evidence page. The exports are simulated with a fixed seed, so the page does not move with the nightly build.
"""
import json

import pandas as pd

from lead_cost.run import CAMPAIGN_COST, CLIENT_COST, FAULTS_FILE, LEAD_MIX, LOAD_AUDIT, SUMMARY, WEEKLY_COST
from lead_cost.simulate import AS_OF, CLIENTS, FIRST_DAY

FILES = (SUMMARY, CAMPAIGN_COST, CLIENT_COST, FAULTS_FILE, LOAD_AUDIT, LEAD_MIX, WEEKLY_COST)
ATTRIBUTED_BY = {  # in the order Gold tries them
    "crm_click_id": "Click id on a CRM record",
    "call_click_id": "Click id call tracking saw",
    "tracking_number": "Tracking number called",
    "none": "Not attributed",
}
SOURCE_LABELS = {
    "search_spend": "Search spend", "social_spend": "Social spend", "search_clicks": "Search clicks",
    "social_clicks": "Social clicks", "calls": "Calls", "tracking_numbers": "Tracking numbers",
    "crm_leads": "CRM leads",
}
# a lead is issued 1-3 days after it arrives and its demo comes 2-10 days after that, so from this week on some
# demos fall after the last day and the week's cost per demo is too high
DEMOS_INCOMPLETE_FROM = pd.Timestamp("2026-06-15").date()


def client_label(client: str) -> str:
    return CLIENTS[client][0]


def _round(x: float) -> float:
    return round(float(x), 2)


def summary_row(s: dict, clients: pd.DataFrame, audit: pd.DataFrame, faults: list[dict]) -> pd.DataFrame:
    h, g, t, slv = s["headline"], s["gold_leads"], s["truth_check"], s["silver"]
    return pd.DataFrame([{
        "first_day": s["first_day"], "as_of": s["as_of"], "clients": len(clients),
        "files": len(audit), "rows_delivered": int(audit["loaded_rows"].sum()),
        "short_files": int((audit["loaded_rows"] < audit["declared_rows"]).sum()),
        "repeated_files": int((audit["batch_id"] != audit["first_batch_with_checksum"]).sum()),
        "spend_rows_dropped": slv["spend_rows_dropped_as_restated_or_repeated"],
        "crm_rows_delivered": slv["crm_rows_delivered"], "crm_records": slv["crm_records"],
        "clicks": slv["clicks"], "calls": slv["calls"],
        "leads": g["leads"], "paid_leads": int(clients["paid_leads"].sum()),
        "unattributed_leads": h["unattributed_leads"], "unattributed_share": g["attributed_by"]["none"] / g["leads"],
        "organic_leads": t["organic_leads"], "paid_unattributed": t["paid_leads_unattributed"],
        "paid_unattributed_issued": t["paid_leads_unattributed_issued"],
        "wrong_campaign": t["attributed_to_the_wrong_campaign"], "outcome_mismatches": t["outcome_mismatches"],
        "spend": h["spend"], "issued_leads": h["paid_issued_leads"], "demos": h["paid_demos"],
        "cost_per_issued_lead": h["cost_per_issued_lead"], "cost_per_demo": _round(h["spend"] / h["paid_demos"]),
        "faults": len(faults), "faults_caught": sum(f["caught"] for f in faults),
    }])


def client_rows() -> pd.DataFrame:
    df = pd.read_csv(CLIENT_COST)
    df.insert(1, "client_label", df["client"].map(client_label))
    df["issued_rate"] = df["issued_leads"] / df["paid_leads"]
    return df


def campaign_rows() -> pd.DataFrame:
    df = pd.read_csv(CAMPAIGN_COST)
    df.insert(2, "client_label", df["client"].map(client_label))
    df.insert(3, "campaign_label", df["client_label"] + ", " + df["platform"] + ": " + df["theme"])
    df["issued_rate"] = df["issued_leads"] / df["leads"]
    return df


def attribution_rows() -> pd.DataFrame:
    """Leads by client, how they came in and how Gold found the campaign, with the rule's order kept for sorting."""
    df = pd.read_csv(LEAD_MIX)
    df.insert(1, "client_label", df["client"].map(client_label))
    df.insert(4, "attributed_by_sort", df["attributed_by"].map(list(ATTRIBUTED_BY).index))
    df.insert(5, "attributed_by_label", df["attributed_by"].map(ATTRIBUTED_BY))
    df["came_by_label"] = df["came_by"].map({"form": "Web form", "call": "Phone call"})
    return df


def weekly_rows() -> pd.DataFrame:
    df = pd.read_csv(WEEKLY_COST)
    df["week"] = pd.to_datetime(df["week"]).dt.date
    df.insert(1, "client_label", df["client"].map(client_label))
    df["cost_per_issued_lead"] = (df["spend"] / df["issued_leads"].where(df["issued_leads"] > 0)).round(2)
    df["cost_per_demo"] = (df["spend"] / df["demos"].where(df["demos"] > 0)).round(2)
    first_monday = FIRST_DAY - pd.Timedelta(days=FIRST_DAY.weekday())
    last_monday = AS_OF - pd.Timedelta(days=AS_OF.weekday())
    df["week_note"] = [
        "starts mid-week" if w == first_monday else "two days only" if w == last_monday
        else "demos not all in yet" if w >= DEMOS_INCOMPLETE_FROM else "" for w in df["week"]]
    return df


def export_rows(audit: pd.DataFrame) -> pd.DataFrame:
    a = audit.assign(short=audit["loaded_rows"] < audit["declared_rows"],
                     repeat=audit["batch_id"] != audit["first_batch_with_checksum"])
    df = a.groupby("source", sort=False).agg(
        files=("batch_id", "size"), declared_rows=("declared_rows", "sum"), loaded_rows=("loaded_rows", "sum"),
        short_files=("short", "sum"), repeated_files=("repeat", "sum"),
        first_delivered=("delivered_at", "min"), last_delivered=("delivered_at", "max")).reset_index()
    df.insert(0, "source_sort", df["source"].map(list(SOURCE_LABELS).index))
    df.insert(2, "source_label", df["source"].map(SOURCE_LABELS))
    for c in ("files", "declared_rows", "loaded_rows", "short_files", "repeated_files"):
        df[c] = df[c].astype(int)
    return df.sort_values("source_sort").reset_index(drop=True)


def audit_rows(audit: pd.DataFrame) -> pd.DataFrame:
    """One row per delivered file, with what the audit says about it in words."""
    df = audit.copy()
    df["delivered_at"] = pd.to_datetime(df["delivered_at"])
    df.insert(2, "source_label", df["source"].map(SOURCE_LABELS))
    df["status"] = [
        f"short: {d - n:,} of {d:,} rows missing" if n < d
        else f"repeat of batch {first} (same checksum)" if b != first else "landed in full"
        for b, d, n, first in zip(df["batch_id"], df["declared_rows"], df["loaded_rows"],
                                  df["first_batch_with_checksum"], strict=True)]
    return df


def fault_rows(faults: list[dict], clean: float) -> pd.DataFrame:
    return pd.DataFrame([{
        "fault_sort": i, "fault": f["fault"], "what": f["what"], "written_to_catch_it": f["written_to_catch_it"],
        "caught": f["caught"], "tests_failed": len(f["failing_tests"]),
        "failing_tests": ", ".join(f["failing_tests"]),
        "cost_per_issued_lead_clean": clean,
        "cost_per_issued_lead_without_tests": f["without_the_tests"]["cost_per_issued_lead"],
        "moves_by": f["cost_per_issued_lead_moves_by"],
        "issued_leads_without_tests": f["without_the_tests"]["paid_issued_leads"],
        "unattributed_without_tests": f["without_the_tests"]["unattributed_leads"],
    } for i, f in enumerate(faults)])


def tables() -> dict[str, pd.DataFrame]:
    """reporting.lead_cost_summary, _clients, _campaigns, _attribution, _weekly, _exports, _load_audit, _faults
    (empty if there are no results)."""
    if not all(p.exists() for p in FILES):
        return {}
    s = json.loads(SUMMARY.read_text(encoding="utf-8"))
    faults = json.loads(FAULTS_FILE.read_text(encoding="utf-8"))
    audit = pd.read_csv(LOAD_AUDIT)
    clients = client_rows()
    return {
        "lead_cost_summary": summary_row(s, clients, audit, faults), "lead_cost_clients": clients,
        "lead_cost_campaigns": campaign_rows(), "lead_cost_attribution": attribution_rows(),
        "lead_cost_weekly": weekly_rows(), "lead_cost_exports": export_rows(audit),
        "lead_cost_load_audit": audit_rows(audit),
        "lead_cost_faults": fault_rows(faults, s["headline"]["cost_per_issued_lead"]),
    }
