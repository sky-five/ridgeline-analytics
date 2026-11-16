"""The margin risk dashboard tables, from the committed results only (no warehouse needed).

`python -m margin_risk` writes results/; scripts/export_reporting.py turns them into reporting.margin_* tables for
the Evidence page. The book is simulated with a fixed seed, so the page does not move with the nightly build.
"""
import json

import pandas as pd

from margin_risk.run import CONCENTRATION, FIRM_DAILY, MARGIN_CALLS, SECTOR_DAILY, SUMMARY

RESOLUTION_LABELS = {"deposit": "Deposit", "liquidated": "Liquidation", "market": "Prices recovered",
                     "open": "Still open"}
CAUSES = {
    "split_applied_late": "The positions file still has SEM03's pre-split quantity on its ex-date",
    "interest_missing_from_cash_file": "May's margin interest is in the ledger but not in the cash file",
}
SNAPSHOT_ORDER = ["first day", "before the sell-off", "end of the sell-off", "last day"]


def _dates(df: pd.DataFrame, *cols: str) -> pd.DataFrame:
    for c in cols:
        df[c] = pd.to_datetime(df[c]).dt.date
    return df


def calls_daily(firm: pd.DataFrame, calls: pd.DataFrame) -> pd.DataFrame:
    """Per weekday: real calls started, calls started on a day that does not reconcile, accounts in call."""
    started = (calls.assign(kind=calls["starts_on_break"].map({False: "real_calls", True: "calls_on_a_break"}))
               .pivot_table(index="call_date", columns="kind", values="account_id", aggfunc="count")
               .reindex(columns=["real_calls", "calls_on_a_break"]))
    out = firm[["as_of_date", "accounts_in_call", "new_calls"]].merge(
        started, left_on="as_of_date", right_index=True, how="left")
    out[["real_calls", "calls_on_a_break"]] = out[["real_calls", "calls_on_a_break"]].fillna(0).astype(int)
    return out


def tables() -> dict[str, pd.DataFrame]:
    """reporting.margin_summary, _daily, _calls, _calls_daily, _call_outcomes, _sectors, _concentration,
    _reconciliation (empty if there are no results)."""
    if not all(p.exists() for p in (SUMMARY, FIRM_DAILY, MARGIN_CALLS, SECTOR_DAILY, CONCENTRATION)):
        return {}
    s = json.loads(SUMMARY.read_text(encoding="utf-8"))
    b, last, c, sh = s["book"], s["last_day"], s["margin_calls"], s["shock"]
    rec, dup = s["checks"]["reconciliation"], s["checks"]["repeated_positions_file"]

    firm = _dates(pd.read_csv(FIRM_DAILY), "as_of_date")
    calls = _dates(pd.read_csv(MARGIN_CALLS), "call_date", "last_day_in_call", "cured_date")
    calls["real"] = ~calls["starts_on_break"]
    calls["resolution_label"] = calls["resolution"].map(RESOLUTION_LABELS)

    real = calls[calls["real"]]
    outcomes = (real.groupby("resolution_label").agg(calls=("account_id", "count"),
                                                      deficit_at_call=("deficit_at_call", "sum"),
                                                      median_weekdays=("weekdays_in_call", "median"))
                .reset_index())

    sectors = _dates(pd.read_csv(SECTOR_DAILY), "as_of_date")
    conc = _dates(pd.read_csv(CONCENTRATION), "as_of_date")
    conc.insert(2, "snapshot_sort", conc["snapshot"].map(SNAPSHOT_ORDER.index))
    conc["snapshot_label"] = conc["snapshot"].str.capitalize() + " (" + conc["as_of_date"].astype(str) + ")"

    cause = {d: f for f, v in rec["faults"].items() for d in v["days"]}
    pnl_check = {u["date"]: u["unexplained"] for u in s["checks"]["unexplained_pnl_days"]}
    recon = pd.DataFrame([{
        "as_of_date": f["date"], "market_value_drift": f["market_value_drift"], "cash_drift": f["cash_drift"],
        "accounts_broken": f["accounts_broken"], "fault": cause.get(f["date"], "unexplained"),
        "cause": CAUSES.get(cause.get(f["date"]), "Not explained yet"),
        "planted": rec["faults"].get(cause.get(f["date"]), {}).get("planted"),
        "pnl_unexplained": pnl_check.get(f["date"]),
    } for f in s["flagged_days"]])
    recon = _dates(recon, "as_of_date")

    summary = pd.DataFrame([{
        "first_day": s["first_day"], "as_of": s["as_of"], "accounts": b["accounts"],
        "margin_accounts": b["margin_accounts"], "weekdays": b["weekdays"], "position_rows": b["position_rows"],
        "account_days": b["weekdays"] * b["accounts"],
        **{k: last[k] for k in ("borrowers", "market_value", "loan", "equity", "collateral_coverage",
                                "margin_utilisation", "concentrated_borrowers", "accounts_in_call")},
        "largest_symbol": s["largest_holding"]["symbol"], "largest_sector": s["largest_holding"]["sector"],
        "largest_share": s["largest_holding"]["share_of_borrower_value"],
        "shock_sector": s["shock_sector"]["sector"], "shock_sector_share": s["shock_sector"]["share"],
        "shock_from": sh["from"], "shock_to": sh["to"], "worst_drop": sh["worst_drop"],
        "mildest_drop": sh["mildest_drop"], "market_pnl_week": sh["market_pnl_week"],
        "calls_within_a_week": sh["real_calls_within_a_week"],
        "real_calls": c["calls"] - c["on_a_break"], "calls_on_a_break": c["on_a_break"],
        "accounts_called": c["accounts"], "calls_before_shock": c["before_shock"],
        "calls_concentrated": c["concentrated"], "deficit_at_call": c["deficit_at_call"],
        "market_pnl": s["pnl"]["market_pnl"], "interest_income": s["pnl"]["interest_income"],
        "deposits": s["pnl"]["deposits"], "worst_day": s["worst_day"]["as_of_date"],
        "worst_day_pnl": s["worst_day"]["market_pnl"],
        "account_days_flagged": rec["account_days_flagged"], "flagged_days": len(s["flagged_days"]),
        "missed": rec["missed"], "false_alarms": rec["false_alarms"],
        "repeated_file_date": dup["date"], "repeated_file_loads": dup["loads"],
        "repeated_file_raw_rows": dup["raw_rows"], "repeated_file_rows_kept": dup["rows_kept"],
        "drift_if_counted_twice": dup["drift_if_counted_twice"],
    }])

    return {
        "margin_summary": summary, "margin_daily": firm, "margin_calls": calls,
        "margin_calls_daily": calls_daily(firm, calls), "margin_call_outcomes": outcomes,
        "margin_sectors": sectors, "margin_concentration": conc, "margin_reconciliation": recon,
    }
