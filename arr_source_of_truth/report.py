"""Tables for the "ARR: CRM to billing" page, from the arr_source_of_truth dbt models.

The ARR warehouse (warehouse/arr.duckdb) is separate from the main one, so this builds it as of a date and
copies the page's tables into the main warehouse's `reporting` schema, where the Evidence site reads them.
Amounts are converted from cents to dollars here; nothing is recomputed.

    python -m arr_source_of_truth.report --as-of 2026-11-11 [--warehouse warehouse/ridgeline.duckdb]
"""
from __future__ import annotations

import argparse
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import duckdb
import pandas as pd

from arr_source_of_truth.load import DEFAULT_DB, dbt_build, load

ROOT = Path(__file__).resolve().parent.parent
MAIN_DB = ROOT / "warehouse" / "ridgeline.duckdb"

# the walk's steps in order: (column in arr_booking_walk, label on the page, kind)
WALK_STEPS = [
    ("crm_booked", "CRM booked", "start"),
    ("duplicates", "Duplicates", "step"),
    ("won_not_billed", "Won, not billed", "step"),
    ("awaiting_billing", "Awaiting billing", "step"),
    ("amount_fixes", "Amount fixes", "step"),
    ("timing", "Timing", "step"),
    ("missing_deals", "Missing deals", "step"),
    ("billing_sales_led", "= Billing new + upgrades", "subtotal"),
    ("seat_changes", "Seat changes", "step"),
    ("cancellations", "Churn and cancellations", "step"),
    ("net_change", "= Net change in ARR", "total"),
]

STATUS_MEANING = {
    "agrees": "Billing started the change the deal describes, at the booked ARR.",
    "annual_at_billed": "Annual plan booked at what the customer pays (10 months), not its ARR (12).",
    "amount_differs": "Billing started the change at a different ARR than the CRM booked.",
    "duplicate": "An unmatched copy of a matched deal for the same customer, within 14 days.",
    "won_not_billed": "Marked won more than 30 days ago; billing never started it.",
    "awaiting_billing": "Closed in the last 30 days; billing has not started it yet.",
}

BRIDGE_COLS = ["opening", "new", "reactivation", "expansion", "contraction", "churn", "closing"]


def _usd(cents: pd.Series) -> pd.Series:
    return cents.astype("int64") / 100


def tables(arr_db: Path, as_of: date) -> dict[str, pd.DataFrame]:
    """The page's tables, read from a built ARR warehouse."""
    with duckdb.connect(str(arr_db), read_only=True) as con:
        walk = con.execute("select * from arr_booking_walk order by month_start").df()
        bridge = con.execute("select * from arr_bridge order by month_start").df()
        deals = con.execute("select * from arr_deal_matches order by close_date, deal_id").df()

    walk_monthly = pd.DataFrame({"month": walk["month_start"].dt.date})
    for col, _, _ in WALK_STEPS:
        walk_monthly[col] = _usd(walk[f"{col}_cents"])

    steps = []
    for r in walk_monthly.itertuples(index=False):
        for order, (col, label, kind) in enumerate(WALK_STEPS, start=1):
            steps.append({"month": r.month, "step_order": order, "step": label, "kind": kind,
                          "usd": getattr(r, col)})

    bridge_out = pd.DataFrame({"month": bridge["month_start"].dt.date})
    for col in BRIDGE_COLS:
        bridge_out[col] = _usd(bridge[f"{col}_arr_cents"])
    bridge_out["paying_customers"] = bridge["paying_customers"].astype("int64")

    deals = deals.assign(booked_usd=_usd(deals["booked_arr_cents"]),
                         billed_usd=deals["billed_arr_cents"].astype("Int64") / 100)
    status = (deals.groupby("status", as_index=False)
              .agg(deals=("deal_id", "count"), booked_usd=("booked_usd", "sum"), billed_usd=("billed_usd", "sum")))
    status["billed_usd"] = status["billed_usd"].astype("float64")
    status["meaning"] = status["status"].map(STATUS_MEANING)
    status["order"] = status["status"].map({s: i for i, s in enumerate(STATUS_MEANING)})
    status = status.sort_values("order").drop(columns="order").reset_index(drop=True)

    flagged = deals.loc[deals["status"] != "agrees",
                        ["deal_id", "customer_id", "deal_type", "close_date", "status", "booked_usd",
                         "billed_usd", "effective_on"]].reset_index(drop=True)
    flagged["billed_usd"] = flagged["billed_usd"].astype("float64")
    flagged["close_date"] = pd.to_datetime(flagged["close_date"]).dt.date
    flagged["effective_on"] = pd.to_datetime(flagged["effective_on"]).dt.date

    last = bridge_out.iloc[-1]
    meta = pd.DataFrame([{
        "as_of": as_of, "last_month": last["month"], "closing_arr": last["closing"],
        "paying_customers": int(last["paying_customers"]), "won_deals": len(deals),
        "deals_matched": int(deals["change_key"].notna().sum()), "deals_flagged": len(flagged),
        "crm_booked_total": walk_monthly["crm_booked"].sum(),
        "billing_sales_led_total": walk_monthly["billing_sales_led"].sum(),
        "built_at": datetime.now(UTC).replace(tzinfo=None, microsecond=0),
    }])
    return {"arr_walk_monthly": walk_monthly, "arr_walk_steps": pd.DataFrame(steps), "arr_bridge": bridge_out,
            "arr_deal_status": status, "arr_deal_flags": flagged, "arr_meta": meta}


def publish(as_of: date, warehouse: Path = MAIN_DB, arr_db: Path = DEFAULT_DB) -> dict[str, int]:
    """Build the ARR warehouse as of `as_of`, then write the page's tables to `warehouse`.reporting."""
    load(as_of, arr_db)
    dbt_build(as_of, arr_db)
    out = tables(arr_db, as_of)
    with duckdb.connect(str(warehouse)) as con:
        con.execute("create schema if not exists reporting")
        for name, df in out.items():
            con.register("_df", df)
            con.execute(f"create or replace table reporting.{name} as select * from _df")
            con.unregister("_df")
    return {name: len(df) for name, df in out.items()}


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m arr_source_of_truth.report")
    p.add_argument("--as-of", type=date.fromisoformat, default=datetime.now(UTC).date() - timedelta(days=1))
    p.add_argument("--warehouse", type=Path, default=MAIN_DB)
    p.add_argument("--arr-db", type=Path, default=DEFAULT_DB)
    args = p.parse_args()
    for name, n in publish(args.as_of, args.warehouse, args.arr_db).items():
        print(f"{name:20}{n:>6,}")


if __name__ == "__main__":
    main()
